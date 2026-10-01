"""Verify output recovery on a private PipeWire/WirePlumber/MPRIS stack.

Run directly; no hardware, host audio services, or public network are used.
Pass --legacy-player --script to compare an older player and --artifacts to retain proof.
"""
import argparse
import ast
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import wave


PROJECT = Path(__file__).resolve().parents[1]
PLUGIN = Path("/usr/lib/mpv-mpris/mpris.so")
SCRIPT = PROJECT / "radio-status.lua"
ARTIFACTS = None
LEGACY_PLAYER = False
REQUIRE_DEPENDENCIES = False
DEPENDENCIES = ("mpv", "pipewire", "pipewire-pulse", "wireplumber", "pactl",
                "parec", "dbus-daemon", "gdbus")


class AudioOutputTest(unittest.TestCase):
    def setUp(self):
        missing = [name for name in DEPENDENCIES if not shutil.which(name)]
        if LEGACY_PLAYER and not PLUGIN.exists():
            missing.append(str(PLUGIN))
        if not LEGACY_PLAYER:
            missing.extend(name for name in ("dbus", "gi") if importlib.util.find_spec(name) is None)
        if missing:
            message = "isolated audio test requires " + ", ".join(missing)
            if REQUIRE_DEPENDENCIES:
                self.fail(message)
            self.skipTest(message)
        # Unix socket paths are limited to 108 bytes, independently of where proof is kept.
        directory = tempfile.TemporaryDirectory(prefix="atlas-audio-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runtime = self.root / "omarchy-radio-atlas"
        self.runtime.mkdir()
        if ARTIFACTS:
            destination = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=ARTIFACTS))
            self.addCleanup(self.retain_artifacts, destination)
        self.processes = []
        self.logs = []
        self.addCleanup(self.stop_processes)
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(self.root),
                        XDG_CONFIG_HOME=str(self.root / "config"),
                        XDG_CACHE_HOME=str(self.root / "cache"),
                        XDG_DATA_HOME=str(self.root / "data"),
                        XDG_STATE_HOME=str(self.root / "state"),
                        PIPEWIRE_RUNTIME_DIR=str(self.root),
                        PIPEWIRE_REMOTE="pipewire-0",
                        PIPEWIRE_CONFIG_DIR="/usr/share/pipewire",
                        WIREPLUMBER_CONFIG_DIR="/usr/share/wireplumber",
                        PULSE_SERVER="unix:" + str(self.root / "pulse/native"),
                        RADIO_ATLAS_STATUS_FILE=str(self.root / "status.json"),
                        RADIO_ATLAS_QUEUE_FILE=str(self.runtime / "playlist.json"))
        bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.processes.append(bus)
        self.addCleanup(bus.stdout.close)
        self.env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
        self.assertTrue(self.env["DBUS_SESSION_BUS_ADDRESS"].startswith("unix:"),
                        "Private D-Bus did not return an address")
        self.start("pipewire")
        self.wait(lambda: (self.root / "pipewire-0").exists())
        # The policy-only profile links synthetic sinks but never discovers hardware.
        self.start("wireplumber", "--profile=policy")
        self.start("pipewire-pulse")
        self.wait(lambda: self.call("pactl", "info"))
        self.selected_module = self.add_sink("atlas_selected")
        self.wait(lambda: self.call("pactl", "set-default-sink", "atlas_selected") or True)
        tone = self.root / "tone.wav"
        with wave.open(str(tone), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"".join(struct.pack("<h", int(10000 * math.sin(
                2 * math.pi * 440 * sample / 8000))) for sample in range(8000 * 90)))
        command = ["mpv", "--no-config", "--load-scripts=no", "--no-video", "--idle=yes",
                   "--no-terminal", "--ao=pipewire", "--audio-device=pipewire/atlas_selected",
                   f"--script={SCRIPT}", f"--log-file={self.root / 'mpv-internal.log'}",
                   f"--input-ipc-server={self.runtime / 'mpv.sock'}", str(tone)]
        if LEGACY_PLAYER:
            command.insert(-1, f"--script={PLUGIN}")
        else:
            command.insert(-1, "--audio-client-name=Radio Atlas")
            command = [sys.executable, str(PROJECT / "radio-mpris"),
                       str(self.runtime / "mpv.sock"), "--", *command]
        self.player = self.start(*command)
        self.wait(lambda: (self.runtime / "mpv.sock").exists())
        self.wait(lambda: (self.property("time-pos") or 0) > 0.3)
        if not LEGACY_PLAYER:
            self.wait(lambda: self.property("user-data/radio-atlas-mpris-ready"))
        self.wait(self.mpris_name)

    def stop_processes(self):
        if (self.runtime / "mpv.sock").exists():
            try:
                self.ipc("quit")
            except (OSError, ValueError):
                pass
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        for log in self.logs:
            log.close()

    def retain_artifacts(self, destination):
        for path in self.root.iterdir():
            if path.is_file() and path.suffix in {".log", ".json", ".jsonl"}:
                shutil.copy2(path, destination / path.name)

    def start(self, *arguments):
        log = (self.root / f"{Path(arguments[0]).name}.log").open("wb")
        self.logs.append(log)
        process = subprocess.Popen(arguments, env=self.env, stdout=log, stderr=log)
        self.processes.append(process)
        return process

    def call(self, *arguments):
        return subprocess.check_output(arguments, env=self.env, text=True,
                                       stderr=subprocess.PIPE, timeout=3).strip()

    def wait(self, predicate, seconds=5):
        deadline = time.monotonic() + seconds
        last_error = None
        while time.monotonic() < deadline:
            try:
                result = predicate()
                if result:
                    return result
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                last_error = error
            time.sleep(0.03)
        logs = "\n".join(path.read_text(errors="replace")[-4000:]
                         for path in self.root.glob("*.log"))
        self.fail(f"Timed out: {last_error}\n{logs}")

    def ipc(self, *command):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(self.runtime / "mpv.sock"))
            connection.sendall((json.dumps(dict(command=command, request_id=1)) + "\n").encode())
            with connection.makefile("r") as replies:
                for line in replies:
                    reply = json.loads(line)
                    if reply.get("request_id") != 1:
                        continue
                    if reply.get("error") != "success":
                        raise ValueError(reply)
                    return reply.get("data")
        raise ValueError("mpv closed IPC without replying")

    def property(self, name):
        return self.ipc("get_property", name)

    def devices(self):
        return {device["name"] for device in self.property("audio-device-list")}

    def add_sink(self, name):
        module = self.call("pactl", "load-module", "module-null-sink", f"sink_name={name}")
        self.wait(lambda: any(sink["name"] == name for sink in json.loads(
            self.call("pactl", "-f", "json", "list", "sinks"))))
        return module

    def remove_selected(self):
        self.call("pactl", "unload-module", self.selected_module)
        self.wait(lambda: "pipewire/atlas_selected" not in self.devices())
        self.wait(lambda: self.property("pause"))

    def restore_selected(self):
        self.selected_module = self.add_sink("atlas_selected")
        self.wait(lambda: "pipewire/atlas_selected" in self.devices())

    def mpris_name(self):
        reply = self.call("gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                          "--object-path", "/org/freedesktop/DBus",
                          "--method", "org.freedesktop.DBus.ListNames")
        return next((name for name in ast.literal_eval(reply)[0]
                     if name.startswith("org.mpris.MediaPlayer2.mpv")), None)

    def mpris_action(self, action):
        self.call("gdbus", "call", "--session", "--dest", self.mpris_name(),
                  "--object-path", "/org/mpris/MediaPlayer2",
                  "--method", "org.mpris.MediaPlayer2.Player." + action)

    def mpris_pause(self):
        self.mpris_action("Pause")
        self.wait(lambda: self.property("pause"))

    def ui_toggle(self):
        self.ipc("script-message", "radio-atlas-toggle")

    def snapshot(self, event, **extra):
        result = dict(event=event, paused=self.property("pause"),
                      time=self.property("time-pos"), output=self.property("audio-device"),
                      devices=sorted(name for name in self.devices() if name.startswith("pipewire/")), **extra)
        with (self.root / "evidence.jsonl").open("a") as output:
            output.write(json.dumps(result) + "\n")
        print(json.dumps(result), flush=True)

    def assert_stays_paused(self, event):
        time.sleep(0.7)  # Exceed the recovery debounce and observe the final state.
        self.snapshot(event)
        self.assertTrue(self.property("pause"))
        position = self.property("time-pos")
        time.sleep(0.15)
        self.assertAlmostEqual(self.property("time-pos"), position, delta=0.02)

    def assert_playing_on_selected(self, event):
        self.wait(lambda: not self.property("pause"))
        position = self.property("time-pos")
        self.wait(lambda: self.property("time-pos") > position + 0.1)
        sinks = json.loads(self.call("pactl", "-f", "json", "list", "sinks"))
        selected = next(sink["index"] for sink in sinks if sink["name"] == "atlas_selected")
        def routed():
            inputs = json.loads(self.call("pactl", "-f", "json", "list", "sink-inputs"))
            return any(stream["sink"] == selected and not stream["corked"] for stream in inputs)
        self.wait(routed)
        monitor = subprocess.Popen(["parec", "--device=atlas_selected.monitor",
                                    "--format=s16le", "--rate=8000", "--channels=1",
                                    "--latency-msec=50", "--process-time-msec=20"],
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes.append(monitor)
        try:
            monitor.communicate(timeout=0.7)
        except subprocess.TimeoutExpired:
            monitor.terminate()
        pcm, error = monitor.communicate(timeout=3)
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[:len(pcm) // 2 * 2])
        peak = max(map(abs, samples), default=0)
        self.assertGreater(peak, 100, f"Selected sink monitor was silent ({len(pcm)} bytes): {error!r}")
        self.snapshot(event, routed_sink="atlas_selected", monitor_peak=peak)

    def test_selected_output_reconnects(self):
        self.assert_playing_on_selected("initial playback")
        for cycle in range(3):
            self.remove_selected()
            self.snapshot(f"cycle {cycle + 1}: selected removed")
            if cycle == 0:
                self.add_sink("atlas_unrelated")
                self.wait(lambda: "pipewire/atlas_unrelated" in self.devices())
                self.assert_stays_paused("unrelated output cannot resume playback")
            self.restore_selected()
            self.snapshot(f"cycle {cycle + 1}: selected reappeared")
            self.assert_playing_on_selected(f"cycle {cycle + 1}: selected returned")

    def check_deliberate_pause(self):
        self.add_sink("atlas_unrelated")
        self.wait(lambda: "pipewire/atlas_unrelated" in self.devices())
        self.assert_stays_paused("after unrelated output while deliberately paused")
        self.remove_selected()
        self.restore_selected()
        self.assert_stays_paused("after selected output returns while deliberately paused")

    def test_mpris_pause_is_preserved(self):
        self.mpris_pause()
        self.snapshot("manual MPRIS pause")
        self.check_deliberate_pause()

    def test_ui_pause_is_preserved(self):
        self.ui_toggle()
        self.wait(lambda: self.property("pause"))
        self.check_deliberate_pause()

    def test_ui_toggle_cancels_recovery(self):
        self.remove_selected()
        self.ui_toggle()
        self.wait(lambda: not self.property("pause"))
        self.ui_toggle()
        self.wait(lambda: self.property("pause"))
        self.restore_selected()
        self.assert_stays_paused("UI pause cancels armed recovery")

    def test_mpris_pause_cancels_recovery_while_already_paused(self):
        self.remove_selected()
        self.mpris_pause()
        self.restore_selected()
        self.assert_stays_paused("repeated human MPRIS Pause cancels policy recovery")

    def test_manual_pause_immediately_before_removal_is_preserved(self):
        self.mpris_pause()
        self.remove_selected()
        self.restore_selected()
        self.assert_stays_paused("human Pause immediately before removal stays paused")

    def test_rapid_output_changes_recover(self):
        for cycle in range(3):
            self.call("pactl", "unload-module", self.selected_module)
            self.selected_module = self.add_sink("atlas_selected")
            self.assert_playing_on_selected(f"rapid cycle {cycle + 1}: selected restored")

    def test_mpris_play_controls_restart_stopped_station(self):
        for _ in range(3):
            self.ipc("loadfile", str(self.root / "tone.wav"), "append")
        self.ipc("playlist-play-index", 1)
        self.wait(lambda: self.property("playlist-pos") == 1 and
                  (self.property("time-pos") or 0) > 0.1)
        for action in ("Play", "PlayPause", "UI"):
            self.mpris_action("Stop")
            self.wait(lambda: self.property("idle-active"))
            self.wait(lambda: json.loads((self.root / "status.json").read_text()).get("stopped"))
            stopped = json.loads((self.root / "status.json").read_text())
            self.assertTrue(stopped["running"])
            self.assertFalse(stopped["loaded"])
            self.mpris_action("Stop")
            if action == "UI":
                self.ui_toggle()
            else:
                self.mpris_action(action)
            self.wait(lambda: (self.property("time-pos") or 0) > 0.1)
            self.wait(lambda: not json.loads((self.root / "status.json").read_text()).get("stopped"))
            self.assertEqual(self.property("playlist-pos"), 1)
            self.assert_playing_on_selected(f"MPRIS Stop then {action}")
        for action, position in [("Next", 2), ("Previous", 1)]:
            self.mpris_action("Pause")
            self.mpris_action("Stop")
            self.mpris_action(action)
            self.wait(lambda: (self.property("time-pos") or 0) > 0.1)
            self.assertEqual(self.property("playlist-pos"), position)
            self.assert_playing_on_selected(f"MPRIS paused then Stop then {action}")

    def test_mpris_volume_is_saved_for_the_next_player_session(self):
        if LEGACY_PLAYER:
            self.skipTest("volume persistence belongs to the Radio Atlas MPRIS bridge")
        self.call(str(PROJECT / "radio-state"), "volume", "40")
        self.ipc("set_property", "volume", 40)
        self.call("gdbus", "call", "--session", "--dest", self.mpris_name(),
                  "--object-path", "/org/mpris/MediaPlayer2",
                  "--method", "org.freedesktop.DBus.Properties.Set",
                  "org.mpris.MediaPlayer2.Player", "Volume", "<0.2>")
        self.assertEqual(self.property("volume"), 20)
        state_file = self.root / "data/radio-atlas/state.json"
        saved = json.loads(state_file.read_text())
        self.snapshot("MPRIS volume changed", volume=self.property("volume"),
                      saved_volume=saved["volume"])
        self.ipc("quit")
        self.player.wait(timeout=5)
        (self.runtime / "mpv.sock").unlink(missing_ok=True)
        binary = self.root / "bin"
        binary.mkdir()
        wrapper = binary / "mpv"
        wrapper.write_text('''#!/usr/bin/env python3
import os
import sys
arguments = [argument for argument in sys.argv[1:] if not argument.startswith("--playlist=")]
os.execv("/usr/bin/mpv", ["mpv", "--no-config", "--ao=pipewire", *arguments,
                          os.environ["RADIO_ATLAS_TEST_TONE"]])
''')
        wrapper.chmod(0o755)
        self.env.update(PATH=f"{binary}:{PROJECT / 'tests/fixtures'}:{self.env['PATH']}",
                        RADIO_ATLAS_TEST_TONE=str(self.root / "tone.wav"))
        uuid = "12345678-1234-1234-1234-123456789abc"
        (self.runtime / "play-selection.json").write_text(json.dumps([
            dict(uuid=uuid, name="Test radio", url="https://example.com/test-radio")]))
        self.addCleanup(self.call, str(PROJECT / "radio-player"), "stop")
        self.call(str(PROJECT / "radio-player"), "play", uuid, "selection")
        self.wait(lambda: self.property("user-data/radio-atlas-mpris-ready"))
        self.wait(lambda: (self.property("time-pos") or 0) > 0.1)
        self.snapshot("player restarted", volume=self.property("volume"),
                      saved_volume=json.loads(state_file.read_text())["volume"])
        self.assertEqual(saved["volume"], 20)
        self.assertEqual(self.property("volume"), 20)

    def test_pending_mpris_volume_keeps_controls_responsive_and_serializes_with_ui(self):
        if LEGACY_PLAYER:
            self.skipTest("asynchronous volume changes belong to the Radio Atlas MPRIS bridge")
        self.call(str(PROJECT / "radio-state"), "volume", "40")
        self.ipc("set_property", "volume", 40)
        command = ["gdbus", "call", "--session", "--dest", self.mpris_name(),
                   "--object-path", "/org/mpris/MediaPlayer2", "--method",
                   "org.freedesktop.DBus.Properties.Set", "org.mpris.MediaPlayer2.Player",
                   "Volume", "<0.2>"]
        with (self.root / "data/radio-atlas/state.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pending = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            self.processes.append(pending)
            self.addCleanup(pending.stdout.close)
            self.addCleanup(pending.stderr.close)
            # Observe the child holding player.lock while its state read waits.
            with (self.runtime / "player.lock").open("w") as player_lock:
                def waiting_for_state():
                    try:
                        fcntl.flock(player_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return True
                    fcntl.flock(player_lock, fcntl.LOCK_UN)
                    return False
                self.wait(waiting_for_state)
            started = time.monotonic()
            self.mpris_action("Pause")
            pause_latency = time.monotonic() - started
            self.assertLess(pause_latency, 0.5)
            self.assertTrue(self.property("pause"))
            self.assertIsNone(pending.poll())
            properties, context = self.media_properties()
            second_replies, second_errors = [], []
            properties.Set("org.mpris.MediaPlayer2.Player", "Volume", 0.3,
                           reply_handler=lambda: second_replies.append(True), error_handler=second_errors.append)
            # This round trip on the same connection confirms Set was received.
            properties.Get("org.mpris.MediaPlayer2.Player", "Rate")
            ui = subprocess.Popen([str(PROJECT / "radio-player"), "volume", "40"],
                                  env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.processes.append(ui)
            self.addCleanup(ui.stdout.close)
            self.addCleanup(ui.stderr.close)
            fcntl.flock(lock, fcntl.LOCK_UN)
        for process in (pending, ui):
            _, error = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, error)
        deadline = time.monotonic() + 5
        while not second_replies and not second_errors and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.001)
        self.assertEqual(second_errors, [])
        self.assertEqual(second_replies, [True])
        self.assertEqual(self.property("volume"), 40)
        saved = json.loads((self.root / "data/radio-atlas/state.json").read_text())["volume"]
        self.assertEqual(saved, 40)
        self.snapshot("overlapping media and UI controls", volume=self.property("volume"),
                      saved_volume=saved, pause_latency_seconds=round(pause_latency, 3),
                      requested_volumes=[20, 30, 40])

    def media_properties(self):
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)
        bus = dbus.bus.BusConnection(self.env["DBUS_SESSION_BUS_ADDRESS"])
        self.addCleanup(bus.close)
        properties = dbus.Interface(bus.get_object(self.mpris_name(), "/org/mpris/MediaPlayer2"),
                                    "org.freedesktop.DBus.Properties")
        return properties, GLib.MainContext.default()

    def test_rapid_media_volume_changes_survive_a_slow_state_lock(self):
        if LEGACY_PLAYER:
            self.skipTest("saved media volume belongs to the Radio Atlas MPRIS bridge")
        self.call(str(PROJECT / "radio-state"), "volume", "40")
        properties, context = self.media_properties()
        replies, errors = [], []
        for volume in [0.2, 0.8]:
            properties.Set("org.mpris.MediaPlayer2.Player", "Volume", volume,
                           reply_handler=lambda: replies.append(True), error_handler=errors.append)
        deadline = time.monotonic() + 5
        while len(replies) + len(errors) < 2 and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.001)
        self.assertEqual(errors, [])
        self.assertEqual(len(replies), 2)
        self.assertEqual(self.property("volume"), 80)
        self.assertEqual(json.loads((self.root / "data/radio-atlas/state.json").read_text())["volume"], 80)
        replies.clear()
        started = time.monotonic()
        with (self.root / "data/radio-atlas/state.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for index in range(200):
                properties.Set("org.mpris.MediaPlayer2.Player", "Volume",
                               (index % 100) / 100,
                               reply_handler=lambda: replies.append(True), error_handler=errors.append,
                               timeout=15)
                deadline = started + (index + 1) / 60
                while time.monotonic() < deadline:
                    context.iteration(False)
                    time.sleep(0.001)
            # Lock contention must not cancel an update after changing live volume.
            while time.monotonic() - started < 5.5:
                context.iteration(False)
                time.sleep(0.001)
            fcntl.flock(lock, fcntl.LOCK_UN)
        deadline = time.monotonic() + 10
        while len(replies) + len(errors) < 200 and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.001)
        self.assertEqual(errors, [])
        self.assertEqual(len(replies), 200)
        saved = json.loads((self.root / "data/radio-atlas/state.json").read_text())["volume"]
        self.assertEqual(self.property("volume"), 99)
        self.assertEqual(saved, 99)
        self.snapshot("rapid media volume changes", requests=200, requests_per_second=60,
                      state_lock_seconds=5.5, volume=self.property("volume"), saved_volume=saved)

    def test_stopping_bridge_cancels_blocked_volume_changes(self):
        if LEGACY_PLAYER:
            self.skipTest("volume workers belong to the Radio Atlas MPRIS bridge")
        self.call(str(PROJECT / "radio-state"), "volume", "40")
        properties, context = self.media_properties()
        replies, errors = [], []
        with (self.root / "data/radio-atlas/state.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for volume in [0.2, 0.3]:
                properties.Set("org.mpris.MediaPlayer2.Player", "Volume", volume,
                               reply_handler=lambda: replies.append(True), error_handler=errors.append)
            properties.Get("org.mpris.MediaPlayer2.Player", "Rate")
            self.player.terminate()
            self.player.wait(timeout=3)
            with (self.runtime / "player.lock").open("w") as player_lock:
                def released():
                    try:
                        fcntl.flock(player_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return False
                    fcntl.flock(player_lock, fcntl.LOCK_UN)
                    return True
                self.wait(released)
            fcntl.flock(lock, fcntl.LOCK_UN)
        deadline = time.monotonic() + 5
        while len(replies) + len(errors) < 2 and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.001)
        self.assertEqual(replies, [])
        self.assertEqual(len(errors), 2)
        saved = json.loads((self.root / "data/radio-atlas/state.json").read_text())["volume"]
        self.assertEqual(saved, 40)
        result = dict(event="bridge stopped with pending volume changes", pending_requests=2,
                      shared_lock_released=True, saved_volume=saved)
        (self.root / "shutdown.json").write_text(json.dumps(result) + "\n")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=SCRIPT)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--legacy-player", action="store_true")
    parser.add_argument("--require-dependencies", action="store_true")
    parser.add_argument("--scenario", choices=("all", "reconnect", "mpris-pause", "ui-pause", "ui-cancel",
                                              "repeated-pause", "pause-before-removal", "rapid-reconnect",
                                              "media-controls", "volume"),
                        default="all")
    options = parser.parse_args()
    SCRIPT = options.script.resolve()
    if not SCRIPT.is_file():
        parser.error(f"script not found: {SCRIPT}")
    ARTIFACTS = options.artifacts
    LEGACY_PLAYER = options.legacy_player
    REQUIRE_DEPENDENCIES = options.require_dependencies
    if ARTIFACTS:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
    scenarios = {"reconnect": "test_selected_output_reconnects",
                 "mpris-pause": "test_mpris_pause_is_preserved",
                 "ui-pause": "test_ui_pause_is_preserved",
                 "ui-cancel": "test_ui_toggle_cancels_recovery",
                 "repeated-pause": "test_mpris_pause_cancels_recovery_while_already_paused",
                 "pause-before-removal": "test_manual_pause_immediately_before_removal_is_preserved",
                 "rapid-reconnect": "test_rapid_output_changes_recover",
                 "media-controls": "test_mpris_play_controls_restart_stopped_station"}
    if options.scenario == "all":
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(AudioOutputTest)
    elif options.scenario == "volume":
        suite = unittest.TestSuite(AudioOutputTest(name) for name in [
            "test_mpris_volume_is_saved_for_the_next_player_session",
            "test_pending_mpris_volume_keeps_controls_responsive_and_serializes_with_ui",
            "test_rapid_media_volume_changes_survive_a_slow_state_lock",
            "test_stopping_bridge_cancels_blocked_volume_changes"])
    else:
        suite = unittest.TestSuite([AudioOutputTest(scenarios[options.scenario])])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
