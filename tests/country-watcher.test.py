"""Exercise the production country-cache watcher with native Quickshell."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

project = Path(__file__).resolve().parents[1]
quickshell = shutil.which('qs') or shutil.which('quickshell')
if not quickshell:
    print('Country watcher test skipped: Quickshell is unavailable')
    raise SystemExit(0)

source = (project / 'RadioAtlas.qml').read_text()
functions = '\n'.join(re.findall(
    r'  function (?:setSelection|setStationList|applyCountryStations|applyCountryCache)\([\s\S]*?\n  \}', source))
watcher = re.search(r'  FileView \{\n    id: countryCacheFile[\s\S]*?\n  \}', source).group()
response = re.search(
    r'else if \(root.fetchAction === "country"\) \{([\s\S]*?)\n      \} else if', source).group(1)
watcher = watcher.replace('    onFileChanged:',
    '    onLoadFailed: { if (root.prepared) console.log("WATCH_READY") }\n    onFileChanged:')
seed = {'uuid': 'cached-station', 'name': 'Cached station', 'url': 'https://example.com/live',
        'countryCode': 'US', 'latitude': 40, 'longitude': -74}
stations = [seed] + [{**seed, 'uuid': f'station-{index}'} for index in range(1, 25)]

with tempfile.TemporaryDirectory(prefix='radio-atlas-country-watcher-') as temporary:
    directory = Path(temporary)
    cache = directory / 'cache' / 'countries'
    runtime = directory / 'runtime'
    runtime.mkdir(mode=0o700)
    (directory / 'RadioModel.js').symlink_to(project / 'RadioModel.js')
    (directory / 'shell.qml').write_text('''import QtQuick
import Quickshell
import Quickshell.Io
import "RadioModel.js" as RadioModel
ShellRoot {
  id: root
  property string mode: "country"
  property string browsedCountryCode: "US"
  property string fetchValue: "US"
  property string countryCachePath: CACHE
  property bool countryCacheLoaded: false
  property bool prepared: false
  property bool reported: false
  property var results: SEED
  property var worldStations: SEED
  property var stations: SEED
  property int worldStationLimit: 5000
  property int selectedIndex: 0
  property var selectedStation: results[0]
  property bool keyboardSelectionVisible: true
  readonly property var displayStations: results
  QtObject {
    id: stationList
    property int currentIndex: 0
    function positionViewAtIndex(index, mode) {}
  }
FUNCTIONS
WATCHER
  function completeCountryFetch() { RESPONSE }
  Process {
    id: prepare
    command: ["mkdir", "-p", root.countryCachePath]
    onExited: function(code) {
      if (code !== 0) throw new Error("Could not prepare isolated cache")
      root.prepared = true
      root.completeCountryFetch()
    }
  }
  Timer {
    interval: 25
    running: true
    repeat: true
    onTriggered: {
      if (root.reported || root.results.length !== 25) return
      if (root.selectedStation.uuid !== "cached-station" || !root.keyboardSelectionVisible)
        throw new Error("Country refresh lost selection")
      root.reported = true
      console.log("WATCH_PASS")
    }
  }
  Component.onCompleted: prepare.running = true
}
'''.replace('CACHE', json.dumps(str(cache)))
       .replace('SEED', json.dumps([seed]))
       .replace('FUNCTIONS', functions).replace('WATCHER', watcher).replace('RESPONSE', response))
    environment = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime),
                   'XDG_CACHE_HOME': str(directory / 'cache'),
                   'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software',
                   'QT_NO_XDG_DESKTOP_PORTAL': '1',
                   'QT_QPA_PLATFORMTHEME': '', 'QT_QUICK_CONTROLS_STYLE': 'Basic'}
    environment.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
    log_path = directory / 'watcher.log'
    with log_path.open('w') as log:
        process = subprocess.Popen([quickshell, '--no-color', '-p', str(directory)],
                                   stdout=log, stderr=subprocess.STDOUT, env=environment)
        try:
            def wait_for(message):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    output = log_path.read_text()
                    if message in output:
                        return
                    if process.poll() is not None:
                        break
                    time.sleep(0.025)
                raise AssertionError(f'Missing {message}:\n{log_path.read_text()}')

            wait_for('WATCH_READY')
            pending = cache / 'refresh.tmp'
            pending.write_text(json.dumps(stations))
            pending.replace(cache / 'US.json')
            wait_for('WATCH_PASS')
        finally:
            process.terminate()
            process.wait(timeout=5)
print('Native country watcher test passed')
