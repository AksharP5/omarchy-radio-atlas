"""Measure globe paint-handler work on the software/offscreen Qt backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

project = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, default=project / "Globe.qml")
parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
args = parser.parse_args()
source = args.source.resolve()
if args.cpu not in os.sched_getaffinity(0):
    parser.error("CPU is outside this process's allowed affinity")
os.sched_setaffinity(0, {args.cpu})

with tempfile.TemporaryDirectory(prefix="atlas-perf-") as temporary:
    directory = Path(temporary)
    globe = source.read_text().replace(
        "  function paintGlobe(ctx) {", "  property var measurements: []\n  function paintGlobe(ctx) {\n    var started = Date.now()")
    globe = globe.replace("    paintGrid(ctx, centreX, centreY, globeRadius)",
                          "    var preparedAt = Date.now()\n    paintGrid(ctx, centreX, centreY, globeRadius)\n    var gridAt = Date.now()")
    globe = globe.replace("    paintCountries(ctx, centreX, centreY, globeRadius)",
                          "    paintCountries(ctx, centreX, centreY, globeRadius)\n    var countriesAt = Date.now()")
    globe = globe.replace("    paintSignals(ctx)", "    paintSignals(ctx)\n    var signalsAt = Date.now()")
    globe = globe.replace("    ctx.stroke()\n  }\n\n  function stationUnderPointer", "    ctx.stroke()\n    measurements.push({prepare: preparedAt - started, grid: gridAt - preparedAt, countries: countriesAt - gridAt, signals: signalsAt - countriesAt, total: Date.now() - started})\n  }\n\n  function stationUnderPointer")
    (directory / "Globe.qml").write_text(globe)
    shutil.copyfile(project / "RadioModel.js", directory / "RadioModel.js")
    shutil.copyfile(project / "assets/countries.json", directory / "countries.json")
    (directory / "tst_profile.qml").write_text('''
import QtQuick
import QtTest

TestCase {
  id: suite
  name: "GlobeProfile"
  when: windowShown
  width: 800
  height: 600
  visible: true
  Globe { id: globe; width: 800; height: 600 }
  function initTestCase() {
    var request = new XMLHttpRequest()
    request.open("GET", Qt.resolvedUrl("countries.json"), false)
    request.send()
    globe.countries = JSON.parse(request.responseText).features
    var stations = []
    for (var i = 0; i < 5000; i++) stations.push({uuid: "s" + i,
      latitude: ((i * 37) % 17000) / 100 - 85,
      longitude: ((i * 67) % 36000) / 100 - 180})
    globe.stations = stations
    waitForRendering(globe)
  }
  function summary(rows, key) {
    var values = rows.map(function(row) { return row[key] }).sort(function(a,b) { return a-b })
    var total = values.reduce(function(sum, value) { return sum + value }, 0)
    return {mean: total / values.length, median: values[Math.floor(values.length / 2)],
      p95: values[Math.floor(values.length * 0.95)], count: values.length}
  }
  function test_profile_data() { return [
    {tag: "world", scale: 1, latitude: 18, longitude: -20},
    {tag: "regional", scale: 3, latitude: 40, longitude: 10},
    {tag: "deep", scale: 12, latitude: 40, longitude: 10}
  ] }
  function test_profile(data) {
    globe.globeScale = data.scale
    globe.centreLatitude = data.latitude
    globe.centreLongitude = data.longitude
    for (var warmup = 0; warmup < 60; warmup++) {
      globe.centreLongitude += 0.17
      waitForRendering(globe)
    }
    globe.measurements = []
    for (var frame = 0; frame < 180; frame++) {
      globe.centreLongitude += 0.17
      waitForRendering(globe)
    }
    var result = {scenario: data.tag}
    var keys = ["prepare", "grid", "countries", "signals", "total"]
    for (var i = 0; i < keys.length; i++) result[keys[i]] = summary(globe.measurements, keys[i])
    console.log("PROFILE " + JSON.stringify(result))
  }
}
''')
    result = subprocess.run(["/usr/lib/qt6/bin/qmltestrunner", "-platform", "offscreen", "-input", str(directory)],
        env={**os.environ, "QT_QUICK_BACKEND": "software", "QT_NO_XDG_DESKTOP_PORTAL": "1", "QT_QPA_PLATFORMTHEME": "", "QML_XHR_ALLOW_FILE_READ": "1"},
        capture_output=True, text=True, timeout=90)
    log = result.stdout + result.stderr
    rows = [json.loads(match) for match in re.findall(r"PROFILE (\{.*\})", log)]
    if result.returncode:
        print(log[-5000:])
        raise SystemExit(result.returncode)
    if len(rows) != 3 or any(row["total"]["count"] != 180 for row in rows):
        raise SystemExit("Incomplete globe paint measurements")
    print(json.dumps({"source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "cpu": args.cpu, "backend": "software/offscreen", "stations": 5000,
                      "warmup_frames": 60, "measured_frames": 180, "measurements": rows}, indent=2))
