"""Verify output recovery on a private PipeWire/WirePlumber/MPRIS stack.

Run directly; no hardware, host audio services, or public network are used.
Pass --script to compare another radio-status.lua and --artifacts to retain proof.
"""
import argparse
import ast
import json
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest
import wave


PROJECT = Path(__file__).resolve().parents[1]
PLUGIN = Path("/usr/lib/mpv-mpris/mpris.so")
SCRIPT = PROJECT / "radio-status.lua"
ARTIFACTS = None
DEPENDENCIES = ("mpv", "pipewire", "pipewire-pulse", "wireplumber", "pactl",
                "parec", "dbus-daemon", "gdbus")


class AudioOutputTest(unittest.TestCase):
    def setUp(self):
        missing = [name for name in DEPENDENCIES if not shutil.which(name)]
        if missing or not PLUGIN.exists():
            self.skipTest("isolated audio test requires " + ", ".join(
                missing + ([] if PLUGIN.exists() else [str(PLUGIN)])))
        if ARTIFACTS:
            self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=ARTIFACTS))
        else:
            directory = tempfile.TemporaryDirectory(prefix="radio-atlas-audio-test-")
            self.addCleanup(directory.cleanup)
            self.root = Path(directory.name)
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
                        RADIO_ATLAS_QUEUE_FILE=str(self.root / "queue.json"))
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
        self.start("mpv", "--no-config", "--no-video", "--idle=yes", "--no-terminal", "--ao=pipewire",
                   "--audio-device=pipewire/atlas_selected", f"--script={SCRIPT}",
                   f"--script={PLUGIN}", f"--log-file={self.root / 'mpv-internal.log'}",
                   f"--input-ipc-server={self.root / 'mpv.sock'}", str(tone))
        self.wait(lambda: (self.root / "mpv.sock").exists())
        self.wait(lambda: (self.property("time-pos") or 0) > 0.3)
        self.wait(self.mpris_name)

    def stop_processes(self):
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
            connection.connect(str(self.root / "mpv.sock"))
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

    def mpris_pause(self):
        self.call("gdbus", "call", "--session", "--dest", self.mpris_name(),
                  "--object-path", "/org/mpris/MediaPlayer2",
                  "--method", "org.mpris.MediaPlayer2.Player.Pause")
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=SCRIPT)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--scenario", choices=("all", "reconnect", "mpris-pause", "ui-pause", "ui-cancel"),
                        default="all")
    options = parser.parse_args()
    SCRIPT = options.script.resolve()
    if not SCRIPT.is_file():
        parser.error(f"script not found: {SCRIPT}")
    ARTIFACTS = options.artifacts
    if ARTIFACTS:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
    scenarios = {"reconnect": "test_selected_output_reconnects",
                 "mpris-pause": "test_mpris_pause_is_preserved",
                 "ui-pause": "test_ui_pause_is_preserved",
                 "ui-cancel": "test_ui_toggle_cancels_recovery"}
    suite = (unittest.defaultTestLoader.loadTestsFromTestCase(AudioOutputTest)
             if options.scenario == "all" else unittest.TestSuite([AudioOutputTest(scenarios[options.scenario])]))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
