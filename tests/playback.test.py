"""Exercise stream failure and recovery with real mpv, without audio or public network."""
import io
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
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
        short, live = audio(1), audio(30)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path == "/broken":
                    self.send_error(503)
                    return
                playlists = {
                    "/playlist.m3u": ["/live", "/alternate"],
                    "/broken.m3u": ["/broken", "/alternate"],
                    "/empty.m3u": [],
                }
                if self.path == "/nested.pls":
                    data = ("[playlist]\nNumberOfEntries=2\n"
                            f"File1=http://127.0.0.1:{self.server.server_port}/playlist.m3u\n"
                            f"File2=http://127.0.0.1:{self.server.server_port}/unused\n"
                            "Version=2\n").encode()
                    content_type = "audio/x-scpls"
                elif self.path in playlists:
                    data = ("#EXTM3U\n" + "".join(
                        f"http://127.0.0.1:{self.server.server_port}{path}\n"
                        for path in playlists[self.path])).encode()
                    content_type = "audio/x-mpegurl"
                else:
                    data = short if self.path == "/short" else live
                    content_type = "audio/wav"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
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

    def start(self, paths, position=0, script=None):
        urls = [f"http://127.0.0.1:{self.server.server_port}{path}" for path in paths]
        queue = [dict(uuid=f"station-{i}", name=path, url=url)
                 for i, (path, url) in enumerate(zip(paths, urls))]
        (self.runtime / "playlist.json").write_text(json.dumps(queue))
        self.log = tempfile.TemporaryFile(mode="w+")
        self.addCleanup(self.log.close)
        process = subprocess.Popen([
            "mpv", "--no-config", "--no-video", "--ao=null", "--idle=yes",
            "--loop-playlist=inf", "--network-timeout=2", f"--playlist-start={position}",
            "--load-unsafe-playlists=no",
            f"--script={script or PROJECT / 'radio-status.lua'}",
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

    def action(self, action, *arguments):
        result = subprocess.run([str(PROJECT / "radio-player"), action, *arguments], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def native_commands(self, *commands):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(self.runtime / "mpv.sock"))
            connection.sendall(b"".join((json.dumps(dict(command=command, request_id=index))
                                        + "\n").encode() for index, command in enumerate(commands)))
            pending = set(range(len(commands)))
            with connection.makefile("r") as replies:
                for line in replies:
                    reply = json.loads(line)
                    if reply.get("request_id") not in pending:
                        continue
                    self.assertEqual(reply.get("error"), "success")
                    pending.remove(reply["request_id"])
                    if not pending:
                        return
            self.fail("mpv closed IPC before replying")

    def hold_disconnect(self):
        script = self.runtime / "held-status.lua"
        script.write_text((PROJECT / "radio-status.lua").read_text() + '''
local pending_end = nil
local disconnected = false
mp.register_event("end-file", function(event) disconnected = event.reason == "eof" end)
mp.add_hook("on_after_end_file", 40, function(hook)
  if not disconnected then return end
  hook:defer()
  pending_end = hook
end)
mp.register_script_message("radio-atlas-test-release-end", function()
  pending_end:cont()
  pending_end = nil
end)
''')
        return script

    def test_navigation_during_disconnect_takes_precedence(self):
        self.start(["/short", "/other"], script=self.hold_disconnect())
        for action in ("next", "previous"):
            self.wait_status(lambda s: s.get("error") == "Stream disconnected")
            self.native_commands(["script-message", "radio-atlas-" + action],
                                 ["script-message", "radio-atlas-test-release-end"])
            state = self.wait_status(lambda s: s.get("loaded") and s["playlistPosition"] == 1)
            self.assertEqual(state["error"], "")
            if action == "next":
                self.native_commands(["playlist-play-index", 0])
        self.assertEqual(self.requests, ["/short", "/other", "/short", "/other"])

    def test_station_replacement_during_disconnect_takes_precedence(self):
        self.start(["/short", "/other"], script=self.hold_disconnect())
        self.wait_status(lambda s: s.get("error") == "Stream disconnected")
        replacement = self.runtime / "replacement.m3u"
        replacement.write_text(f"#EXTM3U\nhttp://127.0.0.1:{self.server.server_port}/replacement\n")
        (self.runtime / "playlist.json").write_text(json.dumps([
            dict(uuid="replacement", name="Replacement station")]))
        self.native_commands(["loadlist", str(replacement), "replace"],
                             ["script-message", "radio-atlas-reload"],
                             ["script-message", "radio-atlas-test-release-end"])
        state = self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "replacement")
        self.assertEqual(state["error"], "")
        self.assertEqual(self.requests, ["/short", "/replacement"])

    def test_selection_waits_for_lua_before_releasing_player_lock(self):
        gate = self.runtime / "failure-stop.fifo"
        os.mkfifo(gate)
        descriptor = os.open(gate, os.O_RDWR | os.O_NONBLOCK)
        self.addCleanup(os.close, descriptor)
        ready = self.runtime / "failure-stop-ready"
        script = self.runtime / "blocked-status.lua"
        # Freeze the exact gap between the failure's identity check and Stop.
        script.write_text((PROJECT / "radio-status.lua").read_text() + f'''
local commandv = mp.commandv
local held = false
mp.commandv = function(command, ...)
  if command == "stop" and failure and not held then
    held = true
    local marker = assert(io.open({json.dumps(str(ready))}, "w")); marker:close()
    local gate = assert(io.open({json.dumps(str(gate))}, "r")); gate:read("*l"); gate:close()
  end
  return commandv(command, ...)
end
''')
        self.start(["/short", "/other"], script=script)
        self.addCleanup(os.write, descriptor, b"release\n")
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists(), "The stream must reach the held failure Stop")
        queue = (self.runtime / "playlist.json").read_text()
        (self.runtime / "play-selection.json").write_text(queue)

        with socket.socket(socket.AF_UNIX) as observer:
            observer.settimeout(3)
            observer.connect(str(self.runtime / "mpv.sock"))
            with subprocess.Popen([str(PROJECT / "radio-player"), "play", "station-1", "selection"],
                                  env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) as player:
                try:
                    with observer.makefile("r") as events:
                        for line in events:
                            event = json.loads(line)
                            if event.get("args", [])[:1] == ["radio-atlas-loadlist"]:
                                break
                    self.assertIsNone(player.poll(), "Enqueuing the Lua message must not complete Play")
                    self.assertEqual((self.runtime / "playlist.json").read_text(), queue)
                    with (self.runtime / "player.lock").open("a") as lock:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    os.write(descriptor, b"release\n")
                    _, error = player.communicate(timeout=5)
                finally:
                    os.write(descriptor, b"release\n")
                    player.kill()
                    player.wait()
        self.assertEqual(player.returncode, 0, error)
        self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-1")
        self.native_commands(["stop", "keep-playlist"],
                             ["script-message", "radio-atlas-clear-failure"])
        self.assertEqual(self.wait_status(lambda s: s.get("stopped"))["error"], "")
        self.assertEqual(self.requests, ["/short", "/other"])

    def test_selection_works_with_a_player_started_before_load_handshake(self):
        source = (PROJECT / "radio-status.lua").read_text()
        start = source.index('mp.register_script_message("radio-atlas-loadlist"')
        end = source.index("local function toggle_playback()", start)
        script = self.runtime / "old-status.lua"
        script.write_text(source[:start] + source[end:])
        self.start(["/live", "/other"], script=script)
        self.wait_status(lambda s: s.get("loaded"))
        (self.runtime / "play-selection.json").write_text((self.runtime / "playlist.json").read_text())
        self.action("play", "station-1", "selection")
        self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-1")
        self.assertEqual(self.requests, ["/live", "/other"])

    def test_failed_lua_playlist_load_preserves_current_queue(self):
        source = (PROJECT / "radio-status.lua").read_text()
        script = self.runtime / "failed-load-status.lua"
        script.write_text(source.replace('mp.commandv("loadlist", path, "replace")',
                                         'mp.commandv("loadlist", path .. ".missing", "replace")'))
        self.start(["/live", "/other"], script=script)
        self.wait_status(lambda s: s.get("loaded"))
        queue = (self.runtime / "playlist.json").read_text()
        (self.runtime / "play-selection.json").write_text(queue)
        result = subprocess.run([str(PROJECT / "radio-player"), "play", "station-1", "selection"],
                                env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual((self.runtime / "playlist.json").read_text(), queue)
        self.assertEqual(self.requests, ["/live"])

    def test_disconnect_overrides_mpv_repeat_and_keep_open(self):
        player, environment = self.prepare_cli()
        (Path(environment["XDG_CONFIG_HOME"]) / "mpv/mpv.conf").write_text(
            "loop-file=inf\nkeep-open=always\n")
        stations = [dict(uuid=f"station-{index}", name=path,
                         url=f"http://127.0.0.1:{self.server.server_port}{path}")
                    for index, path in enumerate(["/short", "/live"])]
        (self.runtime / "results.json").write_text(json.dumps(stations))
        result = subprocess.run([str(player), "play", "station-0"], env=environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log = (self.runtime / "mpv.log").open()
        self.addCleanup(self.log.close)
        state = self.wait_status(lambda s: s.get("error") == "Stream disconnected")
        self.assertEqual(state["station"]["uuid"], "station-0")
        self.assertFalse(state["loaded"])
        self.assertTrue(state["paused"])
        self.assertFalse(state["stopped"])
        # Check the public status command too: it must not erase the Lua failure state.
        self.assertEqual(self.action("status")["error"], "Stream disconnected")
        self.assertEqual(self.requests, ["/short"])
        self.action("toggle")
        self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-0")
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

    def prepare_cli(self):
        root = Path(self.directory.name)
        scripts = root / "scripts"
        scripts.mkdir()
        for name in ("radio-player", "radio-state", "radio-status.lua", "manifest.json"):
            shutil.copy2(PROJECT / name, scripts / name)
        # Keep the real CLI and mpv; bypass session networking for the local stream.
        session = scripts / "radio-session"
        session.write_text('#!/bin/sh\nexec "$@" --ao=null\n')
        session.chmod(0o700)
        config = root / "config/mpv"
        config.mkdir(parents=True)
        fetch = scripts / "radio-fetch"
        fetch.write_text('#!/bin/sh\nprintf "[]\\n"\n')
        fetch.chmod(0o700)
        environment = dict(self.env, XDG_CONFIG_HOME=str(config.parent))
        player = scripts / "radio-player"
        def stop():
            subprocess.run([str(player), "stop"], env=environment,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        self.addCleanup(stop)
        return player, environment

    def test_new_player_starts_playing_when_mpv_config_defaults_to_paused(self):
        player, environment = self.prepare_cli()
        (Path(environment["XDG_CONFIG_HOME"]) / "mpv/mpv.conf").write_text("pause=yes\n")
        station = dict(uuid="startup-station", name="Startup station",
                       url=f"http://127.0.0.1:{self.server.server_port}/live")
        (self.runtime / "results.json").write_text(json.dumps([station]))

        result = subprocess.run([str(player), "play", station["uuid"]],
                                env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log = (self.runtime / "mpv.log").open()
        self.addCleanup(self.log.close)
        state = self.wait_status(lambda s: s.get("loaded"))
        self.assertFalse(state["paused"], "Selecting a station must start playback despite pause=yes in mpv.conf")
        self.assertEqual(state["error"], "")

    def test_system_default_output_overrides_mpv_configured_device(self):
        player, environment = self.prepare_cli()
        (Path(environment["XDG_CONFIG_HOME"]) / "mpv/mpv.conf").write_text(
            "audio-device=pipewire/configured-speaker\n")
        station = dict(uuid="startup-station", name="Startup station",
                       url=f"http://127.0.0.1:{self.server.server_port}/live")
        (self.runtime / "results.json").write_text(json.dumps([station]))

        result = subprocess.run([str(player), "play", station["uuid"]],
                                env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log = (self.runtime / "mpv.log").open()
        self.addCleanup(self.log.close)
        self.assertEqual(self.wait_status(lambda s: s.get("loaded"))["output"], "")

    def test_selected_station_and_queue_override_mpv_playlist_defaults(self):
        player, environment = self.prepare_cli()
        (Path(environment["XDG_CONFIG_HOME"]) / "mpv/mpv.conf").write_text(
            "playlist-start=1\nshuffle=yes\n")
        stations = [dict(uuid=f"station-{index}", name=f"Station {index}",
                         url=f"http://127.0.0.1:{self.server.server_port}/station-{index}")
                    for index in range(3)]
        (self.runtime / "results.json").write_text(json.dumps(stations))

        result = subprocess.run([str(player), "play", "station-0"],
                                env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log = (self.runtime / "mpv.log").open()
        self.addCleanup(self.log.close)
        state = self.wait_status(lambda s: s.get("loaded"))
        self.assertEqual(state["station"]["uuid"], "station-0")
        self.assertEqual(self.requests, ["/station-0"])
        for position in (1, 2):
            self.action("next")
            state = self.wait_status(lambda s: s.get("loaded") and s["playlistPosition"] == position)
            self.assertEqual(state["station"]["uuid"], f"station-{position}")
            self.assertEqual(self.requests[-1], f"/station-{position}")

    def test_stop_cancels_resume_that_is_waiting_for_saved_state(self):
        self.assert_stop_can_run_during_state_read(["resume"], 4)

    def test_stop_cancels_station_start_waiting_for_saved_settings(self):
        self.assert_stop_can_run_during_state_read(["play", "resume-station", "selection"], 4)

    def test_saved_status_read_does_not_block_stop(self):
        self.assert_stop_can_run_during_state_read(["status"], 0)

    def test_overlapping_stops_acknowledge_their_own_generation(self):
        self.assert_stop_can_run_during_state_read(["stop"], 0)

    def assert_stop_can_run_during_state_read(self, arguments, expected_code):
        player, environment = self.prepare_cli()
        root = Path(self.directory.name)
        state_dir = root / "data/radio-atlas"
        state_dir.mkdir(parents=True)
        station = dict(uuid="resume-station", name="Resume station",
                       url=f"http://127.0.0.1:{self.server.server_port}/live")
        (state_dir / "state.json").write_text(json.dumps(dict(favorites=[], recent=[station], volume=70)))
        (self.runtime / "play-selection.json").write_text(json.dumps([station]))
        ready = root / "state-read-ready"
        binary = root / "bin"
        binary.mkdir()
        flock = binary / "flock"
        flock.write_text('#!/bin/sh\nif [ "$2" = 9 ]; then : > "$RADIO_ATLAS_TEST_STATE_READY"; fi\n'
                         'exec /usr/bin/flock "$@"\n')
        flock.chmod(0o700)
        environment.update(PATH=f"{binary}:{environment['PATH']}", RADIO_ATLAS_TEST_STATE_READY=str(ready))

        with (state_dir / "state.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with subprocess.Popen([str(player), *arguments], env=environment, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as play:
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and play.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(), "The command must reach the blocked state read")
                    generation = self.runtime / "player.generation"
                    previous_generation = generation.read_text() if generation.exists() else "0\n"
                    with subprocess.Popen([str(player), "stop"], env=environment, text=True,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as stop:
                        try:
                            deadline = time.monotonic() + 5
                            while (not generation.exists() or generation.read_text() == previous_generation) \
                                    and stop.poll() is None and time.monotonic() < deadline:
                                time.sleep(0.01)
                            self.assertTrue(generation.exists(), "Stop must cancel the pending request")
                            self.assertNotEqual(generation.read_text(), previous_generation,
                                                "The newer Stop must cancel while the state read waits")
                            fcntl.flock(lock, fcntl.LOCK_UN)
                            stopped, stop_error = stop.communicate(timeout=10)
                            play_output, play_error = play.communicate(timeout=10)
                        finally:
                            fcntl.flock(lock, fcntl.LOCK_UN)
                            stop.kill()
                            stop.wait()
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    play.kill()
                    play.wait()
        self.assertEqual(stop.returncode, 0, stop_error)
        self.assertFalse(json.loads(stopped)["running"])
        self.assertEqual(play.returncode, expected_code, play_error)
        if expected_code == 4:
            self.assertIn("Radio playback was canceled", play_error)
        if arguments == ["stop"]:
            self.assertEqual(json.loads(play_output)["stopGeneration"], "1")
            self.assertEqual(json.loads(stopped)["canceledGeneration"], "1")
            self.assertEqual(json.loads(stopped)["stopGeneration"], "2")
        self.assertFalse((self.runtime / "mpv.sock").exists())
        # A genuinely new Resume after Stop still starts the saved station.
        result = subprocess.run([str(player), "resume"], env=environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log = (self.runtime / "mpv.log").open()
        self.addCleanup(self.log.close)
        self.assertFalse(self.wait_status(lambda s: s.get("loaded"))["paused"])

    def test_selecting_station_resumes_paused_playback(self):
        self.start(["/live", "/other"])
        self.wait_status(lambda s: s.get("loaded"))
        self.assertTrue(self.action("toggle")["paused"])
        (self.runtime / "play-selection.json").write_text(
            (self.runtime / "playlist.json").read_text())

        self.assertFalse(self.action("play", "station-1", "selection")["paused"])
        self.wait_status(lambda s: s.get("loaded") and not s["paused"]
                         and s["station"]["uuid"] == "station-1")
        self.assertEqual(self.requests, ["/live", "/other"])

    def test_native_stop_is_visible_and_preserves_station_navigation(self):
        self.start(["/first", "/second", "/third", "/fourth"], position=1)
        self.wait_status(lambda s: s.get("loaded"))
        for action, position, path in [("next", 2, "/third"), ("previous", 1, "/second")]:
            with self.subTest(action=action):
                requests = list(self.requests)
                self.native_commands(["stop", "keep-playlist"])
                stopped = self.wait_status(lambda s: s.get("stopped"))
                self.assertTrue(stopped["running"])
                self.assertFalse(stopped["loaded"])
                self.assertTrue(self.action("status")["stopped"])
                self.action(action)
                resumed = self.wait_status(lambda s: s.get("loaded"))
                self.assertEqual(resumed["playlistPosition"], position)
                self.assertEqual(self.requests, requests + [path])

    def test_stop_clears_failure_and_preserves_navigation(self):
        self.start(["/live", "/broken", "/other"], position=1)
        self.wait_status(lambda s: s.get("error") == "Station could not be played")
        requests = list(self.requests)
        self.native_commands(["stop", "keep-playlist"],
                             ["script-message", "radio-atlas-clear-failure"])
        stopped = self.wait_status(lambda s: s.get("stopped"))
        self.assertEqual(stopped["error"], "")
        self.assertFalse(stopped["loaded"])
        reported = self.action("status")
        self.assertEqual(reported.get("error"), "")
        self.assertTrue(reported["stopped"])
        self.assertEqual(self.requests, requests)
        self.action("next")
        resumed = self.wait_status(lambda s: s.get("loaded"))
        self.assertEqual(resumed["playlistPosition"], 2)
        self.assertEqual(self.requests, requests + ["/other"])

    def test_quick_stop_then_navigation_resumes_paused_station(self):
        self.start(["/first", "/second", "/third", "/fourth"], position=1)
        self.wait_status(lambda s: s.get("loaded"))
        for action, position in [("next", 2), ("previous", 1)]:
            with self.subTest(action=action):
                self.native_commands(["set_property", "pause", True],
                                     ["stop", "keep-playlist"],
                                     ["script-message", "radio-atlas-" + action])
                resumed = self.wait_status(lambda s: s.get("loaded")
                                           and s["playlistPosition"] == position)
                self.assertFalse(resumed["paused"])
        self.assertEqual(self.requests, ["/second", "/third", "/second"])

    def test_navigation_works_with_a_player_started_before_plugin_update(self):
        # Model the old script, which has status reporting but no navigation messages.
        source = (PROJECT / "radio-status.lua").read_text()
        start = source.index("local function navigate(")
        end = source.index('mp.register_event("shutdown"', start)
        script = self.runtime / "old-status.lua"
        script.write_text(source[:start] + source[end:])
        self.start(["/first", "/second", "/third"], position=1, script=script)
        self.wait_status(lambda s: s.get("loaded"))
        for action, position in [("next", 2), ("previous", 1)]:
            self.action(action)
            self.wait_status(lambda s: s.get("loaded") and s["playlistPosition"] == position)
        self.assertEqual(self.requests, ["/second", "/third", "/second"])

    def test_selecting_station_recovers_from_stream_failure(self):
        self.start(["/broken", "/live"])
        self.wait_status(lambda s: s.get("error") == "Station could not be played")
        (self.runtime / "play-selection.json").write_text(
            (self.runtime / "playlist.json").read_text())

        self.action("play", "station-1", "selection")
        state = self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-1")
        self.assertFalse(state["paused"])
        self.assertEqual(state["error"], "")

    def test_nested_playlist_keeps_station_identity_and_navigation(self):
        self.start(["/nested.pls", "/other"])
        state = self.wait_status(lambda s: s.get("loaded"))
        self.assertEqual(state["station"]["uuid"], "station-0")
        self.assertEqual(state["playlistCount"], 2)
        self.action("next")
        state = self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-1")
        self.assertEqual(state["title"], "other")
        self.assertEqual(self.requests, ["/nested.pls", "/playlist.m3u", "/live", "/other"])
        self.action("previous")
        state = self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-0")
        self.assertEqual(state["title"], "live")
        self.assertEqual(self.action("status")["station"]["uuid"], "station-0")

    def test_failed_playlist_stream_keeps_station_selected(self):
        self.start(["/broken.m3u", "/other"])
        state = self.wait_status(lambda s: s.get("error") == "Station could not be played")
        self.assertEqual(state["station"]["uuid"], "station-0")
        self.assertEqual(state["playlistCount"], 2)
        self.action("next")
        state = self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-1")
        self.assertEqual(state["title"], "other")
        self.assertEqual(set(self.requests), {"/broken.m3u", "/broken", "/other"})

    def test_empty_playlist_stays_selected_and_can_be_retried(self):
        self.start(["/empty.m3u", "/other"])
        state = self.wait_status(lambda s: s.get("error") == "Station could not be played")
        self.assertEqual(state["station"]["uuid"], "station-0")
        self.assertEqual(state["errorDetail"], "Station playlist is empty")
        self.assertEqual(self.action("status")["playlistPosition"], 0)
        self.assertEqual(self.requests, ["/empty.m3u"])
        self.action("toggle")
        self.wait_status(lambda s: s.get("error") == "Station could not be played")
        self.assertEqual(self.requests, ["/empty.m3u", "/empty.m3u"])
        self.action("next")
        self.wait_status(lambda s: s.get("loaded") and s["station"]["uuid"] == "station-1")
        self.assertEqual(self.requests, ["/empty.m3u", "/empty.m3u", "/other"])

    def test_status_waiting_for_settings_detects_a_new_player(self):
        root = Path(self.directory.name)
        binary = root / "bin"
        binary.mkdir()
        ready = root / "settings-read-ready"
        wrapper = binary / "flock"
        wrapper.write_text('#!/bin/sh\nif [ "$2" = 7 ]; then : > "$RADIO_ATLAS_TEST_SETTINGS_READY"; fi\n'
                           'exec /usr/bin/flock "$@"\n')
        wrapper.chmod(0o700)
        environment = dict(self.env, PATH=f"{binary}:{self.env['PATH']}",
                           RADIO_ATLAS_TEST_SETTINGS_READY=str(ready))
        with (self.runtime / "settings.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with subprocess.Popen([str(PROJECT / "radio-player"), "status"], env=environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as status:
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and status.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(), "Status must reach the settings lock")
                    self.start(["/live"])
                    self.wait_status(lambda s: s.get("loaded"))
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    output, error = status.communicate(timeout=5)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    status.kill()
                    status.wait()
        self.assertEqual(status.returncode, 0, error)
        self.assertTrue(json.loads(output)["running"])
        self.assertTrue(json.loads(self.status_path.read_text())["loaded"])
        self.assertTrue((self.runtime / "mpv.sock").exists())

    def test_status_command_does_not_overwrite_player_status(self):
        state = dict(running=True, loaded=True, station=dict(uuid="station-0"))
        self.status_path.write_text(json.dumps(state))
        (self.runtime / "playlist.json").write_text('[{"uuid":"station-0"}]')
        server = socket.socket(socket.AF_UNIX)
        self.addCleanup(server.close)
        server.bind(str(self.runtime / "mpv.sock"))
        server.listen(1)

        def reply():
            connection, _ = server.accept()
            with connection, connection.makefile("r") as requests:
                for value in [False, "Test", 0, 1, 70, False, "auto", None]:
                    request = json.loads(requests.readline())
                    response = dict(request_id=request["request_id"], error="success", data=value)
                    connection.sendall((json.dumps(response) + "\n").encode())

        responder = threading.Thread(target=reply, daemon=True)
        responder.start()
        snapshot = self.action("status")
        responder.join(timeout=5)
        self.assertTrue(snapshot["loaded"])
        self.assertEqual(snapshot["title"], "Test")
        self.assertEqual(json.loads(self.status_path.read_text()), state)


if __name__ == "__main__":
    unittest.main()
