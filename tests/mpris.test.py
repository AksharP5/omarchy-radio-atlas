"""Protect source-aware output recovery at the media-control boundary."""
import importlib.machinery
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
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
                                "playlist-pos": 1, "playlist-current-pos": 1,
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
        directory = tempfile.TemporaryDirectory(prefix="atlas-mpris-recovery-")
        self.addCleanup(directory.cleanup)
        runtime = Path(directory.name)
        (runtime / "omarchy-radio-atlas").mkdir()
        patch.dict(os.environ, XDG_RUNTIME_DIR=str(runtime)).start()
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
                                     ("pause", False),
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

    def test_missing_device_at_timer_waits_for_the_next_return(self):
        self.devices()
        self.controls.pause(policy=True)
        self.devices("pipewire/speaker")
        # mpv's native list can change before its observer event is delivered.
        self.ipc.properties["audio-device-list"] = []
        self.run_timers()
        self.assertTrue(self.ipc.properties["pause"])
        self.assertIsNotNone(self.controls.recovery)
        self.devices("pipewire/speaker")
        self.run_timers()
        self.assertFalse(self.ipc.properties["pause"])
        self.assertEqual(self.ipc.commands.count(("set_property", "pause", False)), 1)

    def test_play_and_ui_toggle_use_existing_failure_retry(self):
        self.ipc.properties["idle-active"] = True
        self.ipc.properties["user-data/radio-atlas-failure"] = {"position": 0}
        self.controls.play()
        self.assertEqual(self.ipc.commands[-1], ("script-message", "radio-atlas-perform-toggle"))
        self.controls.toggle()
        self.assertEqual(self.ipc.commands[-1], ("script-message", "radio-atlas-perform-toggle"))

    def test_stop_then_play_and_toggle_restart_the_kept_station(self):
        for resume in [self.controls.play, self.controls.toggle]:
            self.controls.stop()
            self.assertEqual(self.ipc.commands[-1], ("stop", "keep-playlist"))
            self.ipc.properties["playlist-pos"] = -1
            self.ipc.properties["playlist-current-pos"] = -1
            self.ipc.properties["idle-active"] = True
            self.ipc.properties["pause"] = True
            self.controls.stop()
            self.assertEqual(self.controls.stopped_position, 1)
            resume()
            self.assertEqual(self.ipc.commands[-2:], [
                ("playlist-play-index", 1), ("set_property", "pause", False)])
            self.assertIsNone(self.controls.stopped_position)
            self.ipc.properties["playlist-pos"] = 1


class PropertiesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="atlas-mpris-properties-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patcher = patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.root / "runtime"),
                             XDG_DATA_HOME=str(self.root / "data"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state_file = self.root / "data/radio-atlas/state.json"

    def set_property(self, server, name, value):
        server.volume = mpris.VolumeWriter()
        self.addCleanup(server.close)
        replies, errors = [], []
        server.Set(mpris.PLAYER, name, value, lambda: replies.append(True), errors.append)
        deadline = time.monotonic() + 7
        context = mpris.GLib.MainContext.default()
        while not replies and not errors and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.005)
        self.assertTrue(replies or errors, "Asynchronous Set did not reply")
        if errors:
            raise errors[0]

    def test_policy_sender_uses_executable_identity_even_after_an_upgrade(self):
        server = mpris.Mpris.__new__(mpris.Mpris)
        class Daemon:
            def GetConnectionUnixProcessID(self, sender, dbus_interface):
                return 123
        class Bus:
            def get_object(self, *_):
                return Daemon()
        server.bus = Bus()
        for executable, policy in [("/usr/bin/wireplumber", True),
                                   ("/usr/bin/wireplumber (deleted)", True),
                                   ("/usr/bin/playerctl", False)]:
            with self.subTest(executable=executable), patch.object(mpris.os, "readlink", return_value=executable):
                self.assertEqual(server.policy_sender(":1.20"), policy)
        with patch.object(mpris.os, "readlink", side_effect=FileNotFoundError):
            self.assertFalse(server.policy_sender(":1.20"))

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
        ipc.properties["idle-active"] = True
        self.assertEqual(server.Get(mpris.PLAYER, "PlaybackStatus"), "Stopped")
        self.assertEqual(server.Get(mpris.PLAYER, "Metadata"), {})
        with self.assertRaises(mpris.dbus.DBusException):
            server.OpenUri("http://127.0.0.1/private")

    def test_volume_saves_the_rounded_level_and_keeps_other_state(self):
        self.state_file.parent.mkdir(parents=True)
        original = dict(favorites=[dict(uuid="saved-favorite")], recent=[], volume=40)
        self.state_file.write_text(json.dumps(original))
        server = mpris.Mpris.__new__(mpris.Mpris)
        self.set_property(server, "Volume", mpris.dbus.Double(0.305))
        self.assertEqual(json.loads(self.state_file.read_text()), {**original, "volume": 31})

    def test_async_set_keeps_rate_and_volume_validation(self):
        server = mpris.Mpris.__new__(mpris.Mpris)
        self.set_property(server, "Rate", mpris.dbus.Double(1))
        for value in [-0.1, 1.1, float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(mpris.dbus.DBusException):
                self.set_property(server, "Volume", mpris.dbus.Double(value))
        self.assertFalse(self.state_file.exists())

    def test_volume_does_not_overwrite_invalid_state_or_hide_save_failure(self):
        self.state_file.parent.mkdir(parents=True)
        original = '{"favorites":"invalid","recent":[],"volume":40}\n'
        self.state_file.write_text(original)
        server = mpris.Mpris.__new__(mpris.Mpris)
        server.controls = mpris.Controls(MPV(), lambda: None, lambda: None)
        with self.assertRaisesRegex(mpris.dbus.DBusException, "saved state is invalid"):
            self.set_property(server, "Volume", mpris.dbus.Double(0.2))
        self.assertEqual(self.state_file.read_text(), original)

    def test_volume_waits_for_ui_lock_and_saves_the_latest_request(self):
        runtime = self.root / "runtime/omarchy-radio-atlas"
        runtime.mkdir(parents=True)
        server = mpris.Mpris.__new__(mpris.Mpris)
        server.volume = mpris.VolumeWriter()
        self.addCleanup(server.close)
        replies, errors = [], []
        context = mpris.GLib.MainContext.default()
        with (runtime / "player.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for value in [0.2, 0.8]:
                server.Set(mpris.PLAYER, "Volume", mpris.dbus.Double(value),
                           lambda: replies.append(True), errors.append)
            deadline = time.monotonic() + 0.05
            while time.monotonic() < deadline:
                context.iteration(False)
                time.sleep(0.001)
            self.assertEqual(replies, [])
            self.assertFalse(self.state_file.exists())
            fcntl.flock(lock, fcntl.LOCK_UN)
        deadline = time.monotonic() + 5
        while len(replies) + len(errors) < 2 and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.001)
        self.assertEqual(errors, [])
        self.assertEqual(replies, [True, True])
        self.assertEqual(json.loads(self.state_file.read_text())["volume"], 80)


class SessionTest(unittest.TestCase):
    def test_session_starts_mpris_with_a_shadowed_path_python(self):
        directory = tempfile.TemporaryDirectory(prefix="radio-atlas-session-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        runtime = root / "omarchy-radio-atlas"
        runtime.mkdir()
        binary = root / "bin"
        binary.mkdir()
        python = binary / "python3"
        # Model a managed Python without the system dbus/GI site-packages.
        python.write_text('#!/bin/sh\nexec /usr/bin/python3 -S "$@"\n')
        python.chmod(0o755)
        log = tempfile.TemporaryFile(mode="w+")
        self.addCleanup(log.close)

        def stop(process):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

        bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                               stdout=subprocess.PIPE, stderr=log, text=True,
                               start_new_session=True)
        self.addCleanup(bus.stdout.close)
        self.addCleanup(stop, bus)
        address = bus.stdout.readline().strip()
        self.assertTrue(address)
        connection = mpris.dbus.bus.BusConnection(address)
        self.addCleanup(connection.close)
        env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}",
                   XDG_RUNTIME_DIR=str(root), XDG_DATA_HOME=str(root / "data"),
                   DBUS_SESSION_BUS_ADDRESS=address)
        session = subprocess.Popen([
            str(PROJECT / "radio-session"), "mpv", "--no-config", "--no-video",
            "--load-scripts=no", "--idle=yes", "--ao=null",
            f"--input-ipc-server={runtime / 'mpv.sock'}",
        ], env=env, stdout=log, stderr=log, start_new_session=True)
        self.addCleanup(stop, session)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and session.poll() is None:
            if (runtime / "mpv.sock").is_socket() and any(
                str(name).startswith("org.mpris.MediaPlayer2.mpv.radio_atlas.")
                for name in connection.list_names()
            ):
                return
            time.sleep(0.02)
        log.seek(0)
        self.fail(f"Session did not register MPRIS: {log.read()}")


if __name__ == "__main__":
    unittest.main()
