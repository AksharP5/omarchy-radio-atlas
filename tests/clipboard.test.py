"""Clipboard reads are bounded before their text reaches QML."""

import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class ClipboardTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="radio-atlas-clipboard-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.binary = self.root / "wl-paste"
        self.environment = dict(os.environ, PATH=f"{self.root}:{os.environ['PATH']}")

    def read(self, source, *arguments):
        self.binary.write_text("#!/usr/bin/python3\n" + source)
        self.binary.chmod(0o700)
        return subprocess.run([str(PROJECT / "radio-clipboard"), *arguments],
                              env=self.environment, capture_output=True, timeout=5)

    def test_text_is_preserved_and_primary_is_requested_explicitly(self):
        result = self.read('import sys\nassert "--primary" in sys.argv\n'
                           'sys.stdout.buffer.write("日本語 café".encode())\n', "--primary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode(), "日本語 café")

    def test_oversized_and_invalid_text_never_reaches_qml(self):
        for payload in ("b'x' * 4097", "b'\\xff'"):
            with self.subTest(payload=payload):
                result = self.read(f"import sys\nsys.stdout.buffer.write({payload})\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")

    def test_stalled_and_endless_transfers_have_one_overall_deadline(self):
        for source in ("import time\ntime.sleep(60)\n",
                       "import sys,time\nwhile True:\n sys.stdout.write('x'); sys.stdout.flush(); time.sleep(.05)\n"):
            with self.subTest(source=source):
                started = time.monotonic()
                result = self.read(source)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertLess(time.monotonic() - started, 3)

    def test_transfer_failure_never_returns_partial_text(self):
        result = self.read("import sys\nprint('partial'); sys.exit(1)\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
