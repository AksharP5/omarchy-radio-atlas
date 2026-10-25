"""Normalize directory streams with isolated network and storage fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class FetchNormalizationTest(unittest.TestCase):
    def test_empty_resolved_stream_uses_original_url(self):
        cases = [
            ({"url_resolved": ""}, "https://example.com/original"),
            ({"url_resolved": "\r\n\t"}, "https://example.com/original"),
            ({"url_resolved": None}, "https://example.com/original"),
            ({}, "https://example.com/original"),
            ({"url_resolved": "https://example.com/resolved\n"}, "https://example.com/resolved"),
            ({"url_resolved": "file:///tmp/stream"}, None),
            ({"url_resolved": "", "url": "file:///tmp/stream"}, None),
            ({"url_resolved": "", "url": ""}, None),
        ]
        stations = [dict(stationuuid=f"{index:08x}-1234-1234-1234-123456789abc",
                         name=f"Station {index}", countrycode="US",
                         **{"url": "https://example.com/original", **fields})
                    for index, (fields, _) in enumerate(cases)]
        expected = [(station["stationuuid"], url)
                    for station, (_, url) in zip(stations, cases) if url is not None]
        with tempfile.TemporaryDirectory(prefix="radio-atlas-normalization-") as directory:
            root = Path(directory)
            payload = root / "stations.json"
            payload.write_text(json.dumps(stations))
            environment = dict(os.environ, XDG_RUNTIME_DIR=str(root / "runtime"),
                               XDG_CACHE_HOME=str(root / "cache"), XDG_DATA_HOME=str(root / "data"),
                               PATH=f"{PROJECT / 'tests/fixtures'}:{os.environ['PATH']}",
                               RADIO_ATLAS_TEST_CURL_PAYLOAD=str(payload))
            for arguments in [("world-more",),
                              ("resolve", ",".join(station["stationuuid"] for station in stations))]:
                with self.subTest(action=arguments[0]):
                    result = subprocess.run([str(PROJECT / "radio-fetch"), *arguments],
                                            env=environment, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual([(row["uuid"], row["url"]) for row in json.loads(result.stdout)],
                                     expected)


if __name__ == "__main__":
    unittest.main()
