"""Exercise saved queue refresh and history with isolated state and network fixtures."""
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class SavedStationsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="radio-atlas-saved-")
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.runtime = root / "runtime/omarchy-radio-atlas"
        self.runtime.mkdir(parents=True)
        state_dir = root / "data/radio-atlas"
        state_dir.mkdir(parents=True)
        self.state_file = state_dir / "state.json"
        self.payload_file = root / "stations.json"
        self.requests_file = root / "resolve.log"
        self.requests_file.touch()
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(root / "runtime"),
                        XDG_DATA_HOME=str(root / "data"), XDG_CACHE_HOME=str(root / "cache"),
                        PATH=f"{PROJECT / 'tests/fixtures'}:{os.environ['PATH']}",
                        RADIO_ATLAS_TEST_SOCAT_MODE="success",
                        RADIO_ATLAS_TEST_CURL_PAYLOAD=str(self.payload_file),
                        RADIO_ATLAS_TEST_RESOLVE_LOG=str(self.requests_file))
        self.state_file.write_text(json.dumps(dict(favorites=[], recent=[], volume=70)))
        endpoint = socket.socket(socket.AF_UNIX)
        endpoint.bind(str(self.runtime / "mpv.sock"))
        endpoint.close()
        start_time = Path(f"/proc/{os.getpid()}/stat").read_text().split()[21]
        (self.runtime / "player.pid").write_text(f"{os.getpid()} {start_time}\n")

    def run_action(self, script, *arguments):
        result = subprocess.run([str(PROJECT / script), *arguments], env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def save_favorites(self, count, uuid_length=36):
        rows = [dict(uuid=f"{index:08x}-1234-1234-1234-123456789abc".ljust(uuid_length, "a"),
                     name=f"Saved {index}", url=f"https://example.com/retired-{index}")
                for index in range(count)]
        self.state_file.write_text(json.dumps(dict(favorites=rows, recent=[], volume=70)))
        self.payload_file.write_text(json.dumps([
            dict(stationuuid=row["uuid"], name=f"Current {index}",
                 url_resolved=f"https://example.com/current-{index}")
            for index, row in enumerate(rows)
        ]))
        return rows

    def test_favorites_refresh_every_station_without_exceeding_lookup_limit(self):
        for count, uuid_length in [(110, 36), (111, 36), (500, 36), (111, 64)]:
            with self.subTest(favorites=count, uuid_length=uuid_length):
                rows = self.save_favorites(count, uuid_length)
                self.requests_file.write_text("")
                selected = count // 2
                self.run_action("radio-player", "play", rows[selected]["uuid"], "favorites")
                queue = json.loads((self.runtime / "playlist.json").read_text())
                order = list(range(selected, count)) + list(range(selected))
                self.assertEqual([row["uuid"] for row in queue], [rows[i]["uuid"] for i in order])
                for row, index in zip(queue, order, strict=True):
                    self.assertEqual(row["url"], f"https://example.com/current-{index}")
                    self.assertEqual(row["name"], f"Current {index}")
                requests = self.requests_file.read_text().splitlines()
                self.assertTrue(all(len(request) <= 4096 for request in requests))
                self.assertEqual([uuid for request in requests for uuid in request.split(",")],
                                 [row["uuid"] for row in rows])

    def test_failed_later_batch_keeps_the_original_queue(self):
        rows = self.save_favorites(500)
        self.env["RADIO_ATLAS_TEST_RESOLVE_FAIL_UUID"] = rows[-1]["uuid"]
        self.run_action("radio-player", "play", rows[0]["uuid"], "favorites")
        queue = json.loads((self.runtime / "playlist.json").read_text())
        self.assertEqual(queue, rows)
        self.assertGreater(len(self.requests_file.read_text().splitlines()), 1)

    def test_oversized_refresh_keeps_queue_readable_for_status_and_history(self):
        rows = self.save_favorites(500)
        fresh = json.loads(self.payload_file.read_text())
        for row in fresh:
            row.update(homepage="https://example.com/" + "漢" * 2000,
                       favicon="https://example.com/" + "漢" * 2000)
        self.payload_file.write_text(json.dumps(fresh, ensure_ascii=False))
        state = self.run_action("radio-player", "play", rows[0]["uuid"], "favorites")
        self.assertEqual(state["station"].get("uuid"), rows[0]["uuid"])
        queue_file = self.runtime / "playlist.json"
        self.assertEqual(json.loads(queue_file.read_text()), rows)
        state = self.run_action("radio-state", "played", rows[0]["uuid"])
        self.assertEqual(state["recent"], [rows[0]])
        self.assertEqual(json.loads(queue_file.read_text()), rows)

    def test_played_uses_playlist_and_favorite_uses_selection(self):
        uuid = "12345678-1234-1234-1234-123456789abc"
        active = dict(uuid=uuid, name="Current station", url="https://example.com/current")
        selected = dict(uuid=uuid, name="Selected station", url="https://example.com/selected")
        (self.runtime / "playlist.json").write_text(json.dumps([active]))
        (self.runtime / "favorite-selection.json").write_text(json.dumps([selected]))
        state = self.run_action("radio-state", "played", uuid)
        self.assertEqual(state["recent"], [active])
        state = self.run_action("radio-state", "favorite", uuid)
        self.assertEqual(state["favorites"], [selected])
        self.assertEqual(state["recent"], [active])

    def test_history_keeps_station_while_waiting_for_saved_state(self):
        station = dict(uuid="12345678-1234-1234-1234-123456789abc",
                       name="Played station", url="https://example.com/played")
        following = dict(uuid="87654321-4321-4321-4321-cba987654321",
                         name="Following station", url="https://example.com/following")
        for name in ["playlist.json", "results.json"]:
            (self.runtime / name).write_text(json.dumps([station]))
        root = Path(self.directory.name)
        binary = root / "bin"
        binary.mkdir()
        ready = root / "state-lock-requested"
        wrapper = binary / "flock"
        wrapper.write_text('#!/bin/sh\n: > "$RADIO_ATLAS_TEST_LOCK_READY"\n'
                           'exec /usr/bin/flock "$@"\n')
        wrapper.chmod(0o700)
        environment = dict(self.env, PATH=f"{binary}:{self.env['PATH']}",
                           RADIO_ATLAS_TEST_LOCK_READY=str(ready))
        with self.state_file.with_name("state.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with subprocess.Popen([str(PROJECT / "radio-state"), "played", station["uuid"]],
                                  env=environment, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as process:
                try:
                    try:
                        deadline = time.monotonic() + 5
                        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertTrue(ready.exists(), "History never reached saved-state locking")
                        self.assertIsNone(process.poll())
                        for name in ["playlist.json", "results.json"]:
                            (self.runtime / name).write_text(json.dumps([following]))
                        self.state_file.write_text(json.dumps(dict(favorites=[following], recent=[], volume=23)))
                    finally:
                        fcntl.flock(lock, fcntl.LOCK_UN)
                    output, error = process.communicate(timeout=5)
                finally:
                    process.kill()
                    process.wait()
        self.assertEqual(process.returncode, 0, error)
        state = json.loads(output)
        self.assertEqual(state["recent"], [station])
        self.assertEqual(state["favorites"], [following])
        self.assertEqual(state["volume"], 23)

    def test_history_snapshot_rejects_invalid_runtime_arrays(self):
        station = dict(uuid="12345678-1234-1234-1234-123456789abc",
                       name="Station", url="https://example.com/stream")
        for payload in [json.dumps([station] * 501), json.dumps([station]) + "\n[]"]:
            with self.subTest(payload=payload[:60]):
                (self.runtime / "playlist.json").write_text(payload)
                result = subprocess.run([str(PROJECT / "radio-state"), "played", station["uuid"]],
                                        env=self.env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(json.loads(self.state_file.read_text())["recent"], [])

    def test_history_falls_back_to_saved_stations(self):
        rows = self.save_favorites(1)
        state = self.run_action("radio-state", "played", rows[0]["uuid"])
        self.assertEqual(state["recent"], rows)
        self.assertEqual(state["favorites"], rows)


if __name__ == "__main__":
    unittest.main()
