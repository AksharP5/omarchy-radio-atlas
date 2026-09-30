"""Protect source-aware output recovery at the media-control boundary."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_loader("radio_mpris", importlib.machinery.SourceFileLoader(
    "radio_mpris", str(PROJECT / "radio-mpris")))
mpris = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mpris
spec.loader.exec_module(mpris)


class MPV:
    def __init__(self):
        self.properties = dict({"pause": False, "idle-active": False,
                                "audio-device": "pipewire/speaker",
                                "audio-device-list": [{"name": "pipewire/speaker"}]})
        self.commands = []

    def get(self, name, default=None):
        return self.properties.get(name, default)

    def command(self, *command):
        self.commands.append(command)
        if command[0] == "set_property":
            self.properties[command[1]] = command[2]


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.timers = {}
        self.sequence = 0
        self.reset()
        self.addCleanup(patch.stopall)
        patch.object(mpris.GLib, "timeout_add", self.schedule).start()
        patch.object(mpris.GLib, "source_remove", lambda source: self.timers.pop(source, None)).start()

    def reset(self):
        self.ipc = MPV()
        self.controls = mpris.Controls(self.ipc, lambda: None, lambda: None)

    def schedule(self, delay, callback, *args):
        self.assertEqual(delay, 200)
        self.sequence += 1
        self.timers[self.sequence] = (callback, args)
        return self.sequence

    def run_timers(self):
        for source, (callback, args) in list(self.timers.items()):
            self.timers.pop(source)
            self.assertFalse(callback(*args))

    def devices(self, *names):
        devices = [{"name": name} for name in names]
        self.ipc.properties["audio-device-list"] = devices
        self.controls.event(dict(event="property-change", name="audio-device-list", data=devices))

    def test_policy_pause_recovers_for_both_notification_orders_once(self):
        for device_event_first in [False, True]:
            with self.subTest(device_event_first=device_event_first):
                self.reset()
                if device_event_first:
                    self.devices()
                self.controls.pause(policy=True)
                if not device_event_first:
                    self.devices()
                self.devices("pipewire/other")
                self.assertFalse(self.timers)
                self.devices("pipewire/speaker")
                self.assertTrue(self.ipc.properties["pause"])
                self.run_timers()
                self.assertFalse(self.ipc.properties["pause"])
                self.devices("pipewire/speaker")
                self.assertFalse(self.timers)
                self.assertEqual(self.ipc.commands.count(("set_property", "pause", False)), 1)

    def test_human_pause_before_loss_and_repeated_pause_during_loss_stay_paused(self):
        self.controls.pause()
        self.devices()
        self.controls.pause(policy=True)
        self.devices("pipewire/speaker")
        self.run_timers()
        self.assertTrue(self.ipc.properties["pause"])
        self.ipc.properties["pause"] = False
        self.devices()
        self.controls.pause(policy=True)
        self.controls.pause()  # Deliberate Pause must count even when already paused.
        self.devices("pipewire/speaker")
        self.run_timers()
        self.assertTrue(self.ipc.properties["pause"])
        self.assertFalse(self.ipc.commands.count(("set_property", "pause", False)))

    def test_return_observed_before_policy_pause_still_recovers(self):
        self.devices()
        self.devices("pipewire/speaker")
        self.controls.pause(policy=True)
        self.run_timers()
        self.assertFalse(self.ipc.properties["pause"])

    def test_coalesced_device_list_does_not_lose_policy_pause(self):
        # mpv may only report the final present list after a rapid reconnect.
        self.controls.pause(policy=True)
        self.run_timers()
        self.assertFalse(self.ipc.properties["pause"])
        self.assertIsNone(self.controls.recovery)

    def test_default_output_and_already_paused_policy_pause_do_not_arm(self):
        self.ipc.properties["audio-device"] = "auto"
        self.controls.pause(policy=True)
        self.devices("auto")
        self.assertIsNone(self.controls.recovery)
        self.ipc.properties["audio-device"] = "pipewire/speaker"
        self.controls.pause(policy=True)
        self.assertIsNone(self.controls.recovery)

    def test_control_and_station_changes_cancel_pending_recovery(self):
        for event in [dict(event="start-file"), dict(event="end-file"), dict(event="idle"),
                      dict(event="shutdown"), dict(event="property-change", name="audio-device", data="auto"),
                      dict(event="client-message", args=["radio-atlas-ui-toggle"])]:
            with self.subTest(event=event):
                self.ipc.properties["pause"] = False
                self.devices()
                self.controls.pause(policy=True)
                self.devices("pipewire/speaker")
                self.controls.event(event)
                self.assertFalse(self.timers)
                self.assertIsNone(self.controls.recovery)
        for command in [("stop", "keep-playlist"), ("playlist-next", "force"),
                        ("playlist-prev", "force")]:
            self.ipc.properties["pause"] = False
            self.devices()
            self.controls.pause(policy=True)
            self.devices("pipewire/speaker")
            self.controls.action(*command)
            self.assertFalse(self.timers)
            self.assertEqual(self.ipc.commands[-1], command)

    def test_delayed_resume_rechecks_stream_output_pause_and_device(self):
        for property_name, value in [("idle-active", True), ("audio-device", "auto"),
                                     ("pause", False), ("audio-device-list", []),
                                     ("user-data/radio-atlas-failure", {"message": "failed"})]:
            with self.subTest(property_name=property_name):
                self.ipc.properties = MPV().properties
                self.devices()
                self.controls.pause(policy=True)
                self.devices("pipewire/speaker")
                self.ipc.properties[property_name] = value
                before = list(self.ipc.commands)
                self.run_timers()
                self.assertEqual(self.ipc.commands, before)
                self.assertIsNone(self.controls.recovery)

    def test_second_loss_during_guard_delay_waits_for_next_return(self):
        self.devices()
        self.controls.pause(policy=True)
        self.devices("pipewire/speaker")
        self.devices()
        self.assertFalse(self.timers)
        self.devices("pipewire/speaker")
        self.run_timers()
        self.assertFalse(self.ipc.properties["pause"])

    def test_play_and_ui_toggle_use_existing_failure_retry(self):
        self.ipc.properties["idle-active"] = True
        self.ipc.properties["user-data/radio-atlas-failure"] = {"position": 0}
        self.controls.play()
        self.assertEqual(self.ipc.commands[-1], ("script-message", "radio-atlas-perform-toggle"))
        self.controls.toggle()
        self.assertEqual(self.ipc.commands[-1], ("script-message", "radio-atlas-perform-toggle"))

    def test_stop_then_play_and_toggle_restart_the_kept_station(self):
        for resume in [self.controls.play, self.controls.toggle]:
            self.controls.action("stop", "keep-playlist")
            self.ipc.properties["idle-active"] = True
            self.ipc.properties["pause"] = True
            resume()
            self.assertEqual(self.ipc.commands[-2:], [
                ("playlist-play-index", "current"), ("set_property", "pause", False)])


class PropertiesTest(unittest.TestCase):
    def test_root_identity_and_playback_metadata_match_controls(self):
        ipc = MPV()
        ipc.properties.update({"media-title": "Station song", "playlist-pos": 1, "volume": 70})
        server = mpris.Mpris.__new__(mpris.Mpris)
        server.controls = mpris.Controls(ipc, lambda: None, lambda: None)
        root = server.GetAll(mpris.ROOT)
        self.assertEqual(root["Identity"], "Radio Atlas")
        self.assertEqual(root["DesktopEntry"], "")
        playing = server.GetAll(mpris.PLAYER)
        self.assertEqual(playing["PlaybackStatus"], "Playing")
        self.assertEqual(playing["Metadata"]["xesam:title"], "Station song")
        self.assertEqual(playing["Metadata"]["mpris:trackid"], "/org/mpris/MediaPlayer2/track/1")
        self.assertEqual(playing["Volume"], 0.7)
        self.assertFalse(playing["CanSeek"])
        server.controls.pause()
        self.assertEqual(server.Get(mpris.PLAYER, "PlaybackStatus"), "Paused")
        server.Set(mpris.PLAYER, "Volume", mpris.dbus.Double(0.3))
        self.assertEqual(ipc.properties["volume"], 30)
        ipc.properties["idle-active"] = True
        self.assertEqual(server.Get(mpris.PLAYER, "PlaybackStatus"), "Stopped")
        self.assertEqual(server.Get(mpris.PLAYER, "Metadata"), {})
        with self.assertRaises(mpris.dbus.DBusException):
            server.OpenUri("http://127.0.0.1/private")


if __name__ == "__main__":
    unittest.main()
