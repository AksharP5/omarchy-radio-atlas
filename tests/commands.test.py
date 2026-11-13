"""Finite helpers settle failures and deadlines without leaving child processes."""

import fcntl
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class CommandTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="atlas-commands-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def run_command(self, command, seconds=0.3, **kwargs):
        return subprocess.run([sys.executable, str(PROJECT / "radio-run"), str(seconds), *command],
                              capture_output=True, text=True, timeout=5, **kwargs)

    def test_exit_and_launch_failure_are_reported(self):
        good = self.run_command(["/bin/echo", "station"])
        self.assertEqual((good.returncode, good.stdout), (0, "station\n"))
        failed = self.run_command([str(self.root / "missing")])
        self.assertEqual(failed.returncode, 127)

    def test_oversized_output_is_rejected(self):
        result = self.run_command([sys.executable, "-c", "print('x' * 5_000_000)"], seconds=2)
        self.assertEqual(result.returncode, 125)
        self.assertLessEqual(len(result.stdout), 4_194_304)

    def test_timeout_and_cancellation_reap_stubborn_descendants(self):
        for cancel in (False, True, "kill"):
            with self.subTest(cancel=cancel):
                marker = self.root / f"pids-{cancel}"
                script = self.root / "stubborn.py"
                script.write_text('''import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pid = os.fork()
if pid:
    open(sys.argv[1], "w").write(f"{os.getpid()} {pid}")
while True:
    time.sleep(0.01)
''')
                process = subprocess.Popen([sys.executable, str(PROJECT / "radio-run"), "0.3",
                                            sys.executable, str(script), str(marker)],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 2
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(marker.exists())
                    pids = marker.read_text().split()
                    if cancel == "kill":
                        process.kill()
                    elif cancel:
                        process.terminate()
                    process.communicate(timeout=3)
                    expected = -signal.SIGKILL if cancel == "kill" else 125 if cancel else 124
                    self.assertEqual(process.returncode, expected)
                    self.assertTrue(all(not Path(f"/proc/{pid}").exists() for pid in pids))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()

    def test_lock_wait_has_an_overall_deadline_and_can_retry(self):
        state_dir = self.root / "data/radio-atlas"
        state_dir.mkdir(parents=True)
        environment = dict(os.environ, XDG_RUNTIME_DIR=str(self.root),
                           XDG_DATA_HOME=str(self.root / "data"))
        with (state_dir / "state.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.run_command([str(PROJECT / "radio-state"), "get"], env=environment)
            self.assertEqual(result.returncode, 124)
        result = self.run_command([str(PROJECT / "radio-state"), "get"], seconds=2, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_directory_dns_discovery_has_an_overall_deadline(self):
        binary = self.root / "bin"
        binary.mkdir()
        marker = self.root / "dns.pid"
        getent = binary / "getent"
        getent.write_text(f'''#!/usr/bin/python3
import os, pathlib, time
pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))
time.sleep(60)
''')
        getent.chmod(0o700)
        environment = dict(os.environ, XDG_RUNTIME_DIR=str(self.root / "runtime"),
                           XDG_CACHE_HOME=str(self.root / "cache"),
                           XDG_DATA_HOME=str(self.root / "data"),
                           PATH=f"{binary}:{os.environ['PATH']}")
        result = self.run_command([str(PROJECT / "radio-fetch"), "world-more"], env=environment)
        self.assertEqual(result.returncode, 124)
        self.assertTrue(marker.exists())
        self.assertFalse(Path(f"/proc/{marker.read_text()}").exists())

    def test_canceling_output_discovery_stops_the_nested_timeout(self):
        binary = self.root / "bin"
        binary.mkdir()
        marker = self.root / "pactl.pid"
        pactl = binary / "pactl"
        pactl.write_text(f'''#!/usr/bin/python3
import os, pathlib, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))
time.sleep(60)
''')
        pactl.chmod(0o700)
        environment = dict(os.environ, XDG_RUNTIME_DIR=str(self.root / "runtime"),
                           XDG_DATA_HOME=str(self.root / "data"),
                           PATH=f"{binary}:{os.environ['PATH']}")
        result = self.run_command([str(PROJECT / "radio-player"), "outputs"], env=environment)
        self.assertEqual(result.returncode, 124)
        self.assertTrue(marker.exists())
        pid = int(marker.read_text())
        try:
            self.assertFalse(Path(f"/proc/{pid}").exists(), "Canceled output query left pactl running")
        finally:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_native_qml_launch_failure_timeout_and_retry(self):
        quickshell = shutil.which("qs") or shutil.which("quickshell")
        if not quickshell:
            self.skipTest("Quickshell is unavailable")
        for helper in ("RadioProcess.qml", "radio-run"):
            (self.root / helper).symlink_to(PROJECT / helper)
        (self.root / "shell.qml").write_text('''import QtQuick
import Quickshell
ShellRoot {
  property int completions: 0
  RadioProcess {
    id: helper
    timeoutSeconds: 0.2
    command: ["/definitely/missing"]
    onExited: function(code, status) {
      completions++
      console.log("COMPLETE", completions, code, running)
      if (completions === 1 && code === 127) {
        command = ["/bin/sleep", "10"]
        Qt.callLater(function() { helper.running = true })
      } else if (completions === 2 && code === 124) {
        command = ["/bin/sleep", "10"]
        Qt.callLater(function() { helper.running = true; cancel.start() })
      } else if (completions === 3 && code === 125) {
        command = ["/bin/true"]
        Qt.callLater(function() { helper.running = true })
      } else if (completions === 4 && code === 0) {
        console.log("RECOVERED")
        Qt.quit()
      } else Qt.quit()
    }
  }
  Timer {
    id: cancel
    interval: 50
    onTriggered: {
      helper.running = false
      console.log("CANCEL_PENDING", helper.running)
    }
  }
  Component.onCompleted: helper.running = true
}
''')
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                           QT_NO_XDG_DESKTOP_PORTAL="1", QT_QPA_PLATFORMTHEME="")
        result = subprocess.run([quickshell, "--no-color", "-p", str(self.root)], env=environment,
                                capture_output=True, text=True, timeout=6)
        output = result.stdout + result.stderr
        self.assertIn("RECOVERED", output, output)
        self.assertEqual(output.count("qml: COMPLETE"), 4, output)
        self.assertIn("CANCEL_PENDING true", output, output)
        environment["PATH"] = "/definitely/missing"
        result = subprocess.run([quickshell, "--no-color", "-p", str(self.root)], env=environment,
                                capture_output=True, text=True, timeout=4)
        self.assertIn("COMPLETE 1 127 false", result.stdout + result.stderr)

    def test_track_copy_remains_available_after_the_copy_action_returns(self):
        quickshell = shutil.which("qs") or shutil.which("quickshell")
        if not quickshell:
            self.skipTest("Quickshell is unavailable")
        source = (PROJECT / "RadioAtlas.qml").read_text()
        copy = re.search(r"  function copyTrack\([\s\S]*?\n  \}", source).group()
        (self.root / "shell.qml").write_text('''import QtQuick
import Quickshell
ShellRoot {
  id: root
  property string trackCopyText: "日本語 - café"
  property bool trackCopied: false
FUNCTION
  Timer { id: trackCopiedTimer; interval: 1200; onTriggered: root.trackCopied = false }
  Timer {
    interval: 100
    running: true
    onTriggered: {
      if (root.trackCopied && Quickshell.clipboardText === root.trackCopyText)
        console.log("TRACK_COPY_AVAILABLE")
      Qt.quit()
    }
  }
  Component.onCompleted: copyTrack()
}
'''.replace("FUNCTION", copy))
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                           QT_NO_XDG_DESKTOP_PORTAL="1", QT_QPA_PLATFORMTHEME="")
        result = subprocess.run([quickshell, "--no-color", "-p", str(self.root)], env=environment,
                                capture_output=True, text=True, timeout=4)
        self.assertIn("TRACK_COPY_AVAILABLE", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
