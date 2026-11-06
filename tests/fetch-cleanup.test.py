"""Directory downloads clean up after cancellation without stopping cache refreshes."""
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class FetchCleanupTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="radio-atlas-fetch-cleanup-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runtime = self.root / "runtime/omarchy-radio-atlas"
        self.cache = self.root / "cache/omarchy-radio-atlas"
        self.runtime.mkdir(parents=True)
        self.cache.mkdir(parents=True)
        self.processes = []
        self.addCleanup(self.stop_processes)
        binary = self.root / "bin"
        binary.mkdir()
        curl = binary / "curl"
        curl.write_text('''#!/usr/bin/python3
import json, os, pathlib, sys, time
target = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
target.write_text("[" + " " * 262144)
control = pathlib.Path(os.environ["RADIO_ATLAS_TEST_CONTROL"])
marker = control / ("." + str(os.getpid()))
marker.write_text(str(target))
marker.rename(control / str(os.getpid()))
while not (control / "release").exists():
    time.sleep(0.01)
if os.environ.get("RADIO_ATLAS_TEST_FAIL") == "1":
    raise SystemExit(22)
target.write_text(json.dumps([dict(stationuuid="12345678-1234-1234-1234-123456789abc",
    name="Refreshed station", url="https://example.com/live", countrycode="US",
    geo_lat=40, geo_long=-74)]))
''')
        curl.chmod(0o700)
        self.env = dict(os.environ, HOME=str(self.root), XDG_RUNTIME_DIR=str(self.root / "runtime"),
                        XDG_CACHE_HOME=str(self.root / "cache"), XDG_DATA_HOME=str(self.root / "data"),
                        PATH=f"{binary}:{PROJECT / 'tests/fixtures'}:{os.environ['PATH']}")

    def stop_processes(self):
        for process in self.processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in self.processes:
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(f"Fetch did not finish; remaining files: {list(self.runtime.rglob('*'))}")

    def start(self, action, control, *, fail=False):
        control.mkdir()
        process = subprocess.Popen([str(PROJECT / "radio-fetch"), *action],
                                   env=dict(self.env, RADIO_ATLAS_TEST_CONTROL=str(control),
                                            RADIO_ATLAS_TEST_FAIL="1" if fail else "0"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        self.processes.append(process)
        return process

    def downloads(self, control):
        return [Path(marker.read_text()) for marker in control.iterdir() if marker.name.isdigit()]

    def test_cancelled_expansion_preserves_another_active_download(self):
        first_control = self.root / "first"
        second_control = self.root / "second"
        first = self.start(["world-more"], first_control)
        second = self.start(["world-more"], second_control)
        self.wait_for(lambda: len(self.downloads(first_control)) == 1
                      and len(self.downloads(second_control)) == 1)
        first_download = self.downloads(first_control)[0]
        second_download = self.downloads(second_control)[0]
        first.terminate()
        first.communicate(timeout=5)
        self.assertFalse(first_download.exists(), "Cancel must discard the partial response")
        self.assertTrue(second_download.exists(), "Other downloads must keep their own temporary files")
        (second_control / "release").touch()
        output, error = second.communicate(timeout=5)
        self.assertEqual(second.returncode, 0, error)
        self.assertEqual(json.loads(output)[0]["name"], "Refreshed station")
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_parallel_search_requests_clean_up_together(self):
        control = self.root / "search"
        process = self.start(["search", "jazz"], control)
        self.wait_for(lambda: len(self.downloads(control)) == 3)
        (control / "release").touch()
        output, error = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, error)
        self.assertEqual(len(json.loads(output)), 1)
        self.assertEqual([path.name for path in self.runtime.iterdir()], ["results.json"])

    def test_long_retry_after_uses_another_directory_mirror(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if len(requests) == 1:
                    self.send_response(503)
                    self.send_header("Retry-After", "60")
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps([dict(
                    stationuuid="12345678-1234-1234-1234-123456789abc",
                    name="Available mirror", url="https://example.com/live", countrycode="US"
                )]).encode())

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop_server():
            server.shutdown()
            server.server_close()
            worker.join()

        self.addCleanup(stop_server)
        self.use_real_curl(f"http://127.0.0.1:{server.server_port}")
        process = self.start(["country", "US"], self.root / "retry")
        output, error = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, error)
        self.assertEqual(json.loads(output)[0]["name"], "Available mirror")
        self.assertEqual(len(requests), 2)

    def use_real_curl(self, server_url):
        real_curl = shutil.which("curl")
        curl = self.root / "bin/curl"
        # Keep curl's retry behavior while routing requests only to the local server.
        curl.write_text('''#!/usr/bin/python3
import os, sys
from urllib.parse import urlsplit
arguments = sys.argv[1:]
server = os.environ["RADIO_ATLAS_TEST_SERVER"]
arguments[arguments.index("--proto") + 1] = "=" + urlsplit(server).scheme
for index, argument in enumerate(arguments):
    if argument.startswith("https://"):
        arguments[index] = server + urlsplit(argument).path
real_curl = REAL_CURL
os.execv(real_curl, [real_curl, "--disable", "--noproxy", "*", *arguments])
'''.replace("REAL_CURL", json.dumps(real_curl)))
        curl.chmod(0o700)
        self.env["RADIO_ATLAS_TEST_SERVER"] = server_url

    def test_tls_resets_retry_a_single_directory_mirror(self):
        certificate = self.root / "certificate.pem"
        key = self.root / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(certificate), "-days", "1",
                        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
                       check=True, capture_output=True, timeout=10)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        connections = []

        class Server(ThreadingHTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(5)
                connections.append(address)
                if len(connections) != 4:
                    # Reset after ClientHello so real curl reports TLS error 35.
                    connection.recv(1)
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                          struct.pack("ii", 1, 0))
                    connection.close()
                    raise ConnectionResetError("Test TLS reset")
                return context.wrap_socket(connection, server_side=True), address

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps([dict(
                    stationuuid="12345678-1234-1234-1234-123456789abc",
                    name="Recovered station", url="https://example.com/live", countrycode="US",
                    geo_lat=40, geo_long=-74
                )]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        server = Server(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop_server():
            server.shutdown()
            server.server_close()
            worker.join()

        self.addCleanup(stop_server)
        self.use_real_curl(f"https://127.0.0.1:{server.server_port}")
        self.env["CURL_CA_BUNDLE"] = str(certificate)
        # Empty discovery forces the single fallback mirror, as in a fresh install.
        getent = self.root / "bin/getent"
        getent.write_text("#!/bin/sh\nexit 2\n")
        getent.chmod(0o700)

        process = self.start(["world"], self.root / "recover")
        output, error = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, error)
        self.assertEqual(json.loads(output)[0]["name"], "Recovered station")
        self.assertEqual(len(connections), 4)
        cached = (self.cache / "world.json").read_text()
        self.assertEqual(json.loads(cached), json.loads(output))

        process = self.start(["world-more"], self.root / "exhaust")
        output, error = process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("curl: (35)", error)
        self.assertEqual(output, "")
        self.assertEqual(len(connections), 8, "Stop after three retries")
        self.assertEqual((self.cache / "world.json").read_text(), cached)
        self.assertEqual(sorted(path.name for path in self.runtime.iterdir()),
                         ["results.json", "world.json"])

    def test_detached_refresh_owns_its_download_after_cached_response_exits(self):
        # jq 1.6 succeeds on an empty input stream; it must not erase a cache.
        jq = self.root / "bin/jq"
        jq.write_text('''#!/usr/bin/python3
import os, subprocess, sys
if len(sys.argv) == 3 and sys.argv[1] == "-ce":
    data = sys.stdin.buffer.read()
    if not data:
        raise SystemExit(0)
    raise SystemExit(subprocess.run(["/usr/bin/jq", *sys.argv[1:]], input=data).returncode)
os.execv("/usr/bin/jq", ["jq", *sys.argv[1:]])
''')
        jq.chmod(0o700)
        cached = [dict(uuid="12345678-1234-1234-1234-123456789abc", name="Cached station",
                       url="https://example.com/cached", countryCode="US", latitude=40, longitude=-74)]
        for action, relative in [(["world"], "world.json"), (["country", "US"], "countries/US.json")]:
            for fail in (False, True):
                with self.subTest(action=action, failed=fail):
                    target = self.cache / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(cached))
                    os.utime(target, (1, 1))
                    control = self.root / f"{action[0]}-{fail}"
                    process = self.start(action, control, fail=fail)
                    output, error = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, error)
                    self.assertEqual(json.loads(output), cached)
                    self.wait_for(lambda: len(self.downloads(control)) == 1)
                    self.assertTrue(self.downloads(control)[0].exists(),
                                    "Parent exit must not remove an active cache refresh's response")
                    (control / "release").touch()
                    self.wait_for(lambda: not any(self.runtime.glob("fetch.*"))
                                  and not any(self.runtime.glob("request.*"))
                                  and not any(self.runtime.glob("response.*")))
                    self.assertEqual(json.loads(target.read_text())[0]["name"],
                                     "Cached station" if fail else "Refreshed station")

    def test_busy_refresh_lock_leaves_no_download_files(self):
        flock = self.root / "bin/flock"
        flock.write_text('''#!/bin/bash
/usr/bin/flock "$@"
status=$?
printf '%s' "$status" > "$RADIO_ATLAS_TEST_CONTROL/lock-result"
exit "$status"
''')
        flock.chmod(0o700)
        cached = [dict(uuid="12345678-1234-1234-1234-123456789abc", name="Cached station",
                       url="https://example.com/cached", countryCode="US")]
        for action, relative, lock_relative in [(["world"], "world.json", "world.lock"),
                                                (["country", "US"], "countries/US.json", "countries/US.lock")]:
            with self.subTest(action=action):
                target = self.cache / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(cached))
                os.utime(target, (1, 1))
                control = self.root / f"locked-{action[0]}"
                with (self.cache / lock_relative).open("w") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    process = self.start(action, control)
                    output, error = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, error)
                    self.assertEqual(json.loads(output), cached)
                    result = control / "lock-result"
                    self.wait_for(lambda: result.exists() and result.read_text() == "1")
                    self.wait_for(lambda: not any(self.runtime.glob("fetch.*")))
                    self.assertEqual(self.downloads(control), [])


if __name__ == "__main__":
    unittest.main()
