"""Protect source-aware output recovery at the media-control boundary."""
import importlib.machinery
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from unittest.mock import Mock, patch


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


class IPCTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="atlas-mpris-ipc-")
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / "mpv.sock")
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(path)
            listener.listen(1)
            # Invoke the watch directly so stale readiness is deterministic.
            with patch.object(mpris.GLib, "io_add_watch", return_value=None):
                self.ipc = mpris.IPC(path)
            self.peer, _ = listener.accept()
        self.addCleanup(self.ipc.close)
        self.addCleanup(self.peer.close)
        self.ipc.socket.settimeout(0.05)  # Bound a regression's blocking recv.

    def test_stale_readiness_after_command_keeps_the_connection_alive(self):
        reply = dict(request_id=1, error="success", data=70)
        self.peer.sendall((json.dumps(reply) + "\n").encode())
        self.assertEqual(self.ipc.get("volume"), 70)
        self.assertTrue(self.ipc.readable(None, mpris.GLib.IO_IN))
        self.assertEqual(list(self.ipc.events), [])

    def test_readable_preserves_events_and_reports_disconnect(self):
        event = dict(event="property-change", name="pause", data=True)
        self.peer.sendall((json.dumps(event) + "\n").encode())
        self.peer.close()
        self.assertFalse(self.ipc.readable(None, mpris.GLib.IO_IN | mpris.GLib.IO_HUP))
        self.assertEqual(list(self.ipc.events), [event, dict(event="shutdown")])


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
            self.assertEqual(self.ipc.commands[-2:], [
                ("stop", "keep-playlist"), ("script-message", "radio-atlas-clear-failure")])
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

    def test_delayed_start_file_after_stop_keeps_the_stopped_station(self):
        self.controls.stop()
        self.ipc.properties.update({"playlist-pos": -1, "idle-active": True})
        self.controls.event(dict(event="start-file"))

        self.controls.play()

        self.assertEqual(self.ipc.commands[-2:], [
            ("playlist-play-index", 1), ("set_property", "pause", False)])

    def test_new_station_load_replaces_the_stopped_resume_position(self):
        self.controls.stop()
        self.ipc.properties.update({"playlist-pos": 2, "idle-active": False})
        self.controls.event(dict(event="start-file"))
        self.ipc.properties.update({"playlist-pos": -1, "idle-active": True})

        self.controls.play()

        self.assertEqual(self.ipc.commands[-2:], [
            ("playlist-play-index", "current"), ("set_property", "pause", False)])


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
        self.addCleanup(server.volume.close)
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
        server.artwork = mpris.Artwork(server.controls, lambda: None)
        self.addCleanup(server.artwork.close)
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

    def test_station_artwork_never_exports_a_remote_url(self):
        runtime = self.root / "runtime/omarchy-radio-atlas"
        runtime.mkdir(parents=True)
        (runtime / "playlist.json").write_text(json.dumps([
            dict(uuid="station", favicon="http://127.0.0.1/private.png")]))
        ipc = MPV()
        ipc.properties["playlist-pos"] = 0
        server = mpris.Mpris.__new__(mpris.Mpris)
        server.controls = mpris.Controls(ipc, lambda: None, lambda: None)
        server.artwork = mpris.Artwork(server.controls, lambda: None)
        self.addCleanup(server.artwork.close)
        metadata = server.GetAll(mpris.PLAYER)["Metadata"]
        self.assertNotIn("mpris:artUrl", metadata)

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
        self.addCleanup(server.volume.close)
        replies, errors = [], []
        context = mpris.GLib.MainContext.default()
        with (runtime / "settings.lock").open("w") as lock:
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


class ArtworkTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="atlas-artwork-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runtime = self.root / "runtime/omarchy-radio-atlas"
        self.runtime.mkdir(parents=True)
        self.queue = self.runtime / "playlist.json"
        environment = patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.root / "runtime"),
                                 XDG_CACHE_HOME=str(self.root / "cache #?"), RADIO_ATLAS_ALLOW_FAKE_IP="false")
        environment.start()
        self.addCleanup(environment.stop)
        self.ipc = MPV()
        self.ipc.properties["playlist-pos"] = 0
        self.controls = mpris.Controls(self.ipc, lambda: None, lambda: None)
        self.changed = Mock()
        self.artwork = mpris.Artwork(self.controls, self.changed)
        self.addCleanup(self.artwork.close)
        self.downloads = []
        def start(command, flags):
            process = Mock()
            process.communicate_utf8_finish.return_value = (True, None, "")
            process.get_successful.return_value = True
            self.downloads.append((process, command))
            return process
        patcher = patch.object(mpris.Gio.Subprocess, "new", side_effect=start)
        patcher.start()
        self.addCleanup(patcher.stop)

    def station(self, url):
        temporary = self.queue.with_suffix(".next")
        temporary.write_text(json.dumps([dict(uuid="station", favicon=url)]))
        temporary.replace(self.queue)
        self.artwork.update(0, True)

    def finish(self, index):
        process, command = self.downloads[index]
        target = Path(command[command.index(str(PROJECT / "radio-favicon")) + 2])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
        callback = process.communicate_utf8_async.call_args.args[2]
        callback(process, object())
        return target.as_uri()

    def test_artwork_is_local_and_controls_work_while_the_download_is_pending(self):
        self.station("https://icons.example/image.svg")
        self.assertEqual(self.artwork.uri, "")
        self.controls.pause()
        self.assertTrue(self.ipc.properties["pause"])
        expected = self.finish(0)
        self.assertEqual(self.artwork.uri, expected)
        self.assertIn("cache%20%23%3F", expected)
        self.assertEqual(self.ipc.properties["user-data/radio-atlas-artwork"], expected)
        self.changed.assert_called_once()
        self.artwork.update(0, True)
        self.assertEqual(len(self.downloads), 1)

    def test_same_position_queue_replacement_rejects_old_download(self):
        self.station("https://icons.example/old.svg")
        first = self.downloads[0][0]
        self.station("https://icons.example/new.svg")
        first.send_signal.assert_called_once_with(signal.SIGTERM)
        self.finish(0)
        self.assertEqual(self.artwork.uri, "")
        expected = self.finish(1)
        self.assertEqual(self.artwork.uri, expected)

    def test_stop_and_failure_clear_artwork_and_ignore_late_completion(self):
        self.station("https://icons.example/image.svg")
        self.finish(0)
        self.artwork.update(0, False)
        self.assertEqual(self.artwork.uri, "")
        self.assertEqual(self.ipc.properties["user-data/radio-atlas-artwork"], "")
        self.artwork.update(0, True)
        self.ipc.properties["user-data/radio-atlas-failure"] = dict(message="failed")
        self.finish(1)
        self.assertEqual(self.artwork.uri, "")

    def test_failed_downloads_are_not_retried_on_metadata_updates(self):
        self.station("https://icons.example/image.svg")
        self.downloads[0][0].get_successful.return_value = False
        self.finish(0)
        for _ in range(10):
            self.artwork.update(0, True)
        self.assertEqual(self.artwork.uri, "")
        self.assertEqual(len(self.downloads), 1)

    def test_queue_is_read_once_until_it_changes_and_is_bounded(self):
        self.station("https://icons.example/image.svg")
        with patch.object(Path, "open", side_effect=AssertionError("queue was read again")):
            for _ in range(100):
                self.artwork.update(0, True)
        for data in ([dict(favicon="https://icons.example/image.svg")] * 501, {"favicon": "https://icons.example/image.svg"}):
            self.queue.write_text(json.dumps(data))
            self.artwork.update(0, True)
            self.assertEqual(self.artwork.uri, "")
            self.assertEqual(self.artwork.urls, [])
        with self.queue.open("wb") as source:
            source.truncate(4_194_305)
        self.artwork.update(0, True)
        self.assertEqual(self.artwork.urls, [])

    def test_session_fake_ip_opt_in_is_forwarded_to_downloader(self):
        with patch.dict(os.environ, RADIO_ATLAS_ALLOW_FAKE_IP="true"):
            self.artwork = mpris.Artwork(self.controls, self.changed)
        self.addCleanup(self.artwork.close)
        self.station("https://icons.example/image.svg")
        self.assertIn("--allow-fake-ip", self.downloads[0][1])


class SessionTest(unittest.TestCase):
    def setUp(self):
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

        self.root, self.runtime, self.binary, self.log = root, runtime, binary, log

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
                   XDG_CACHE_HOME=str(root / "cache #?"),
                   DBUS_SESSION_BUS_ADDRESS=address)
        self.connection, self.env, self.stop = connection, env, stop

    def start_session(self, *arguments):
        session = subprocess.Popen([
            str(PROJECT / "radio-session"), "mpv", "--no-config", "--no-video",
            "--load-scripts=no", "--idle=yes", "--ao=null",
            f"--input-ipc-server={self.runtime / 'mpv.sock'}", *arguments,
        ], env=self.env, stdout=self.log, stderr=self.log, start_new_session=True)
        self.addCleanup(self.stop, session)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and session.poll() is None:
            names = [str(name) for name in self.connection.list_names()
                     if str(name).startswith("org.mpris.MediaPlayer2.mpv.radio_atlas.")]
            if (self.runtime / "mpv.sock").is_socket() and names:
                return self.connection.get_object(names[0], mpris.OBJECT)
            time.sleep(0.02)
        self.log.seek(0)
        self.fail(f"Session did not register MPRIS: {self.log.read()}")

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.02)
        self.log.seek(0)
        status = self.runtime / "status.json"
        state = status.read_text() if status.exists() else "missing"
        self.fail(f"Timed out waiting for session artwork: {self.log.read()}\nStatus: {state}")

    def test_session_starts_mpris_with_a_shadowed_path_python(self):
        self.start_session()

    def test_fake_ip_artwork_reaches_mpris_and_both_status_paths_without_blocking_controls(self):
        state = self.root / "data/radio-atlas/state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps(dict(favorites=[], recent=[], volume=70, allowFakeIp=True)))
        queue = self.runtime / "playlist.json"
        queue.write_text(json.dumps([dict(uuid="station", name="Station", favicon="http://198.18.1.2/image.svg")]))
        image = self.root / "image.svg"
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="blue"/></svg>')
        started, release = self.root / "download-started", self.root / "download-release"
        curl = self.binary / "curl"
        curl.write_text('''#!/bin/sh
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then output=$2; shift 2; else shift; fi
done
head -c 500000 /dev/zero > "$output"
printf '%s\n' "$$" >> "$RADIO_ATLAS_TEST_ART_STARTED"
while [ ! -f "$RADIO_ATLAS_TEST_ART_RELEASE" ]; do sleep 0.01; done
cp "$RADIO_ATLAS_TEST_ART_IMAGE" "$output"
printf '200 '
''')
        curl.chmod(0o700)
        status = self.runtime / "status.json"
        self.env.update(RADIO_ATLAS_TEST_ART_STARTED=str(started),
                        RADIO_ATLAS_TEST_ART_RELEASE=str(release), RADIO_ATLAS_TEST_ART_IMAGE=str(image),
                        RADIO_ATLAS_STATUS_FILE=str(status), RADIO_ATLAS_QUEUE_FILE=str(queue))
        tone = self.root / "tone.wav"
        with wave.open(str(tone), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * 8000 * 30)
        server = self.start_session("--loop-playlist=inf", f"--script={PROJECT / 'radio-status.lua'}", str(tone))
        properties = mpris.dbus.Interface(server, mpris.PROPERTIES)
        player = mpris.dbus.Interface(server, mpris.PLAYER)
        self.wait(started.exists)
        self.assertNotIn("mpris:artUrl", properties.GetAll(mpris.PLAYER)["Metadata"])
        player.Pause(timeout=1)
        self.assertEqual(properties.GetAll(mpris.PLAYER)["PlaybackStatus"], "Paused")
        cache = self.root / "cache #?/omarchy-radio-atlas/favicons"
        partial = next(cache.glob(".favicon.*"))
        player.Next()
        self.wait(lambda: len(started.read_text().splitlines()) >= 2)
        self.wait(lambda: not partial.exists())
        self.assertEqual(len(list(cache.glob(".favicon.*"))), 1, "Cancellation must remove the old partial image")
        release.touch()
        artwork = str(self.wait(lambda: properties.GetAll(mpris.PLAYER)["Metadata"].get("mpris:artUrl")))
        self.assertTrue(artwork.startswith("file:///"))
        self.assertIn("cache%20%23%3F", artwork)
        self.wait(lambda: status.exists() and json.loads(status.read_text()).get("artwork") == artwork)
        result = subprocess.run([str(PROJECT / "radio-player"), "status"], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["artwork"], artwork)
        previous_write = status.stat().st_mtime_ns
        player.Next()
        self.wait(lambda: status.stat().st_mtime_ns != previous_write)
        self.wait(lambda: json.loads(status.read_text()).get("artwork") == artwork)
        self.assertEqual(len(started.read_text().splitlines()), 2, "Cached replay must not download again")
        self.assertEqual(list(cache.glob(".favicon.*")), [])

        queue.write_text(json.dumps([dict(uuid="other-station", favicon="http://127.0.0.1/private.svg")]))
        with socket.socket(socket.AF_UNIX) as ipc:
            ipc.settimeout(2)
            ipc.connect(str(self.runtime / "mpv.sock"))
            ipc.sendall(b'{"command":["script-message","radio-atlas-reload"],"request_id":1}\n')
            ipc.recv(4096)
        self.wait(lambda: "mpris:artUrl" not in properties.GetAll(mpris.PLAYER)["Metadata"])
        self.wait(lambda: json.loads(status.read_text()).get("artwork") == "")
        player.Play()
        player.Stop()
        self.assertEqual(properties.GetAll(mpris.PLAYER)["Metadata"], {})


if __name__ == "__main__":
    unittest.main()
