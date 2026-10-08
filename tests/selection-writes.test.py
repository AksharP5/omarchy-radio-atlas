"""Native selection writes must succeed before Play or Favorite uses them."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

project = Path(__file__).resolve().parents[1]
quickshell = shutil.which("qs") or shutil.which("quickshell")
if not quickshell:
    if "--require-dependencies" in sys.argv:
        raise RuntimeError("Selection write test requires Quickshell")
    print("Selection write test skipped: Quickshell is unavailable")
    raise SystemExit(0)

source = (project / "RadioAtlas.qml").read_text()
functions = "\n".join(re.findall(
    r"  function (?:writeSelection|playStation|toggleFavorite|startNextFavorite)\([\s\S]*?\n  \}", source))
views = "\n".join(re.search(
    rf"  FileView \{{\n    id: {name}[\s\S]*?\n  \}}", source).group()
    for name in ["playSelectionFile", "favoriteSelectionFile"])
writer = re.search(r"  Process \{\n    id: stateProcess[\s\S]*?\n  \}", source).group()
writer = writer.replace("onExited: function(exitCode) {", 'onExited: function(exitCode) {\n      console.log("OPERATION_DONE")')
old = dict(uuid="11111111-1234-1234-1234-111111111111", name="Old station", url="https://example.com/old")
current = dict(old, name="Current station", url="https://example.com/current")

with tempfile.TemporaryDirectory(prefix="radio-atlas-selection-writes-") as temporary:
    directory = Path(temporary)
    runtime = directory / "runtime/omarchy-radio-atlas"
    runtime.mkdir(parents=True, mode=0o700)
    data = directory / "data/radio-atlas"
    data.mkdir(parents=True)
    state = data / "state.json"
    state.write_text(json.dumps(dict(favorites=[], recent=[], volume=23)))
    for name in ["play-selection.json", "favorite-selection.json"]:
        (runtime / name).write_text(json.dumps([old]))
    (runtime / "playlist.json").write_text(json.dumps([current]))
    blocked = directory / "blocked"
    blocked.write_text("Not a directory")
    control = directory / "control"
    control.write_text("")
    calls = directory / "calls"
    calls.write_text("")
    wrappers = {}
    for action in ["player", "state"]:
        wrapper = directory / action
        wrapper.write_text("#!/usr/bin/python3\nimport json, subprocess, sys\nfrom pathlib import Path\n"
            + f"result = subprocess.run({[str(project / ('radio-' + action))]!r} + sys.argv[1:], capture_output=True, text=True)\n"
            + f"with Path({str(calls)!r}).open('a') as output:\n"
            + f"    output.write(json.dumps(dict(action={action!r}, args=sys.argv[1:], code=result.returncode, error=result.stderr)) + '\\n')\n"
            + "print(result.stdout)\nsys.exit(result.returncode)\n")
        wrapper.chmod(0o700)
        wrappers[action] = str(wrapper)
    (directory / "RadioModel.js").symlink_to(project / "RadioModel.js")
    qml = '''import QtQuick
import Quickshell
import Quickshell.Io
import "RadioModel.js" as RadioModel
ShellRoot {
  id: root
  property string playSelectionPath: PLAY_SELECTION
  property string favoriteSelectionPath: FAVORITE_SELECTION
  property string playerPath: PLAYER_PATH
  property string statePath: STATE_PATH
  property bool playerActionBusy: playerActionProcess.running
  property bool playCancellationRequested: false
  property string activePlayGeneration: "0"
  property string playerError: ""
  property bool remoteMode: true
  property var displayStations: ROWS
  property var pendingFavoriteRequests: []
  property bool localReloadPending: false
  property string localError: ""
  function playerGeneration() { return "0" }
  function cancelPendingPlay() {}
  function highlightStationCountry(station, focusGlobe) {}
  function applyLocalState(raw) {}
  function refreshLocalSelection() {}
  function requestLocalStateReload() {}
FUNCTIONS
VIEWS
WRITER
  Process {
    id: playerActionProcess
    property string action: ""
    property string output: ""
    property string errorOutput: ""
    command: []
    onExited: console.log("OPERATION_DONE")
  }
  FileView {
    path: CONTROL
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var request = JSON.parse(text() || "null")
      if (!request) return
      if (request.rows) root.displayStations = request.rows
      if (request.action === "play") root.playSelectionPath = request.path
      else root.favoriteSelectionPath = request.path
      if (request.action === "play") root.playStation(root.displayStations[0], "world", root.displayStations)
      else {
        root.remoteMode = request.remote !== false
        root.toggleFavorite(root.displayStations[0].uuid)
      }
      Qt.callLater(function() {
        console.log("SUBMITTED", JSON.stringify({label: request.label, playerError: root.playerError,
          localError: root.localError, busy: playerActionProcess.running || stateProcess.running}))
      })
    }
  }
}
'''
    replacements = dict(PLAY_SELECTION=str(runtime / "play-selection.json"),
                        FAVORITE_SELECTION=str(runtime / "favorite-selection.json"),
                        PLAYER_PATH=wrappers["player"], STATE_PATH=wrappers["state"], CONTROL=str(control))
    replacements = {key: json.dumps(value) for key, value in replacements.items()}
    replacements.update(ROWS=json.dumps([current]), FUNCTIONS=functions, VIEWS=views, WRITER=writer)
    for key, value in replacements.items():
        qml = re.sub(rf"\b{key}\b", lambda match: value, qml)
    (directory / "shell.qml").write_text(qml)
    environment = dict(os.environ, XDG_RUNTIME_DIR=str(directory / "runtime"),
                       XDG_DATA_HOME=str(directory / "data"), XDG_CACHE_HOME=str(directory / "cache"),
                       PATH=f"{project / 'tests/fixtures'}:{os.environ['PATH']}",
                       RADIO_ATLAS_TEST_SOCAT_MODE="success", RADIO_ATLAS_TEST_SOCKET=str(runtime / "mpv.sock"),
                       QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_NO_XDG_DESKTOP_PORTAL="1", QT_QPA_PLATFORMTHEME="", QT_QUICK_CONTROLS_STYLE="Basic")
    environment.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(runtime / "mpv.sock"))
    log_path = directory / "selection.log"
    with log_path.open("w") as log:
        process = subprocess.Popen([quickshell, "--no-color", "-p", str(directory)],
                                   env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            def wait_for(predicate):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    if process.poll() is not None:
                        break
                    time.sleep(0.025)
                raise AssertionError(f"Selection operation did not finish:\n{log_path.read_text()}\n{calls.read_text()}")

            def submit(label, action, path, **options):
                update = directory / "control.tmp"
                update.write_text(json.dumps(dict(label=label, action=action, path=str(path), **options)))
                update.replace(control)
                wait_for(lambda: f'"label":"{label}"' in log_path.read_text())
                return json.loads(re.search(r'SUBMITTED (.*"label":"' + label + r'".*)', log_path.read_text()).group(1))

            # A previous successful write must not authorize a later failed write.
            for action in ["play", "favorite"]:
                path = runtime / ("play-selection.json" if action == "play" else "favorite-selection.json")
                for attempt in range(2):
                    count = len(calls.read_text().splitlines())
                    completed = log_path.read_text().count("OPERATION_DONE")
                    submit(f"{action}-success-{attempt}", action, path, rows=[current])
                    wait_for(lambda: len(calls.read_text().splitlines()) == count + 1)
                    wait_for(lambda: log_path.read_text().count("OPERATION_DONE") == completed + 1)
                    result = json.loads(calls.read_text().splitlines()[-1])
                    assert result["code"] == 0, result
                    assert result["args"][-1] == "selection", result
                    assert json.loads(path.read_text()) == [current], path.read_text()
                before = calls.read_text()
                saved = state.read_text()
                retry = dict(current, url="https://example.com/retry")
                for attempt in range(2):
                    report = submit(f"{action}-failed-{attempt}", action, blocked / "snapshot.json", rows=[retry])
                    assert not report["busy"], report
                    assert report["playerError" if action == "play" else "localError"], report
                    assert calls.read_text() == before, calls.read_text()
                    assert state.read_text() == saved, state.read_text()
                count = len(calls.read_text().splitlines())
                completed = log_path.read_text().count("OPERATION_DONE")
                report = submit(f"{action}-recovered", action, path, rows=[retry])
                wait_for(lambda: len(calls.read_text().splitlines()) == count + 1)
                wait_for(lambda: log_path.read_text().count("OPERATION_DONE") == completed + 1)
                assert json.loads(calls.read_text().splitlines()[-1])["code"] == 0
                assert json.loads(path.read_text()) == [retry], path.read_text()
                assert not report["playerError" if action == "play" else "localError"], report
            # Local Favorite uses current playback, not an old remote snapshot.
            saved = json.loads(state.read_text())
            saved["favorites"] = []
            state.write_text(json.dumps(saved))
            (runtime / "playlist.json").write_text(json.dumps([current]))
            (runtime / "favorite-selection.json").write_text(json.dumps([old]))
            count = len(calls.read_text().splitlines())
            submit("favorite-local", "favorite", blocked / "snapshot.json", remote=False, rows=[current])
            wait_for(lambda: len(calls.read_text().splitlines()) == count + 1)
            assert json.loads(state.read_text())["favorites"] == [current], state.read_text()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            listener.close()
print("Native selection write tests passed")
