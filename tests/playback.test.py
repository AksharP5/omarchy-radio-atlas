"""Exercise stream failure and recovery with real mpv, without audio or public network."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PROJECT = Path(__file__).resolve().parents[1]


def audio(seconds):
    data = io.BytesIO()
    with wave.open(data, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * int(8000 * seconds))
    return data.getvalue()


class PlaybackTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="radio-atlas-playback-")
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        runtime = root / "omarchy-radio-atlas"
        runtime.mkdir()
        self.status_path = runtime / "status.json"
        self.requests = []
        requests = self.requests
        short, live = audio(0.2), audio(30)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path == "/broken":
                    self.send_error(503)
                    return
                data = short if self.path == "/short" else live
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(root), XDG_DATA_HOME=str(root / "data"),
                        RADIO_ATLAS_STATUS_FILE=str(self.status_path),
                        RADIO_ATLAS_QUEUE_FILE=str(runtime / "playlist.json"))
        self.runtime = runtime

    def start(self, paths, position=0):
        urls = [f"http://127.0.0.1:{self.server.server_port}{path}" for path in paths]
        queue = [dict(uuid=f"station-{i}", name=path, url=url)
                 for i, (path, url) in enumerate(zip(paths, urls))]
        (self.runtime / "playlist.json").write_text(json.dumps(queue))
        self.log = tempfile.TemporaryFile(mode="w+")
        self.addCleanup(self.log.close)
        process = subprocess.Popen([
            "mpv", "--no-config", "--no-video", "--ao=null", "--idle=yes",
            "--loop-playlist=inf", "--network-timeout=2", f"--playlist-start={position}",
            f"--script={PROJECT / 'radio-status.lua'}",
            f"--input-ipc-server={self.runtime / 'mpv.sock'}", *urls,
        ], env=self.env, stdout=self.log, stderr=self.log)

        def stop():
            process.terminate()
            process.wait(timeout=5)

        self.addCleanup(stop)

    def wait_status(self, predicate):
        deadline = time.monotonic() + 6
        state = {}
        while time.monotonic() < deadline:
            if self.status_path.exists():
                state = json.loads(self.status_path.read_text())
                if predicate(state):
                    return state
            time.sleep(0.02)
        self.log.seek(0)
        self.fail(f"Status did not match: {state}\n{self.log.read()}")

    def action(self, action):
        result = subprocess.run([str(PROJECT / "radio-player"), action], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_disconnect_stays_selected_and_retry_reopens_same_stream(self):
        self.start(["/short", "/live"])
        state = self.wait_status(lambda s: s.get("error") == "Stream disconnected")
        self.assertEqual(state["station"]["uuid"], "station-0")
        self.assertFalse(state["loaded"])
        self.assertTrue(state["paused"])
        # Check the public status command too: it must not erase the Lua failure state.
        self.assertEqual(self.action("status")["error"], "Stream disconnected")
        self.assertEqual(self.requests, ["/short"])
        self.action("toggle")
        self.wait_status(lambda s: s.get("error") == "Stream disconnected")
        self.assertEqual(self.requests, ["/short", "/short"])
        self.action("next")
        state = self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-1")
        self.assertEqual(state["error"], "")
        self.assertFalse(state["paused"])
        self.action("toggle")
        self.wait_status(lambda s: s["paused"])
        self.action("toggle")
        self.wait_status(lambda s: not s["paused"])

    def test_open_failure_stays_selected_and_previous_uses_failed_position(self):
        self.start(["/live", "/broken", "/other"], position=1)
        state = self.wait_status(lambda s: s.get("error") == "Station could not be played")
        self.assertEqual(state["playlistPosition"], 1)
        self.assertTrue(state["errorDetail"])
        state = self.action("status")
        self.assertEqual(state["station"]["uuid"], "station-1")
        self.assertTrue(self.requests)
        self.assertEqual(set(self.requests), {"/broken"})
        failed_requests = list(self.requests)
        self.action("status")
        self.assertEqual(self.requests, failed_requests)
        self.action("previous")
        self.wait_status(lambda s: s.get("loaded") and s["playlistPosition"] == 0)
        self.assertEqual(self.requests, failed_requests + ["/live"])


if __name__ == "__main__":
    unittest.main()
