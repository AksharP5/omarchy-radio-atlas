"""Keep queued Recent metadata with native Quickshell and real saved-state locking."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

project = Path(__file__).resolve().parents[1]
quickshell = shutil.which("qs") or shutil.which("quickshell")
if not quickshell:
    if "--require-dependencies" in sys.argv:
        raise RuntimeError("History queue test requires Quickshell")
    print("History queue test skipped: Quickshell is unavailable")
    raise SystemExit(0)

source = (project / "RadioAtlas.qml").read_text()
functions = "\n".join(re.findall(
    r"  function (?:recordPlayed|startRecordPlayed|writeSelection)\([\s\S]*?\n  \}", source))
views = "\n".join(re.search(
    rf"  FileView \{{\n    id: {name}[\s\S]*?\n  \}}", source).group()
    for name in ["historyPlaylistFile", "historySelectionFile"])
writer = re.search(r"  Process \{\n    id: historyProcess[\s\S]*?\n  \}", source).group()
first = dict(uuid="11111111-1234-1234-1234-111111111111", name="First", url="https://example.com/first")
queued = dict(uuid="22222222-1234-1234-1234-222222222222", name="Queued", url="https://example.com/queued")
following = dict(uuid="33333333-1234-1234-1234-333333333333", name="Following", url="https://example.com/following")

with tempfile.TemporaryDirectory(prefix="radio-atlas-history-queue-") as temporary:
    directory = Path(temporary)
    runtime = directory / "runtime/omarchy-radio-atlas"
    runtime.mkdir(parents=True, mode=0o700)
    state_dir = directory / "data/radio-atlas"
    state_dir.mkdir(parents=True)
    state = state_dir / "state.json"
    state.write_text(json.dumps(dict(favorites=[following], recent=[], volume=23)))
    playlist = runtime / "playlist.json"
    playlist.write_text(json.dumps([first]))
    control = directory / "control"
    control.write_text("")
    marker = directory / "state-lock-requested"
    binary = directory / "bin"
    binary.mkdir()
    wrapper = binary / "flock"
    wrapper.write_text('#!/bin/sh\n: > "$RADIO_ATLAS_TEST_LOCK_READY"\nexec /usr/bin/flock "$@"\n')
    wrapper.chmod(0o700)
    (directory / "RadioModel.js").symlink_to(project / "RadioModel.js")
    (directory / "shell.qml").write_text('''import QtQuick
import Quickshell
import Quickshell.Io
import "RadioModel.js" as RadioModel
ShellRoot {
  id: root
  property string runtimePath: RUNTIME
  property string statePath: STATE
  property var pendingRecentRequest: null
  property bool localReloadPending: false
  property string localError: ""
  onLocalErrorChanged: console.log("LOCAL_ERROR", localError)
  function requestLocalStateReload() {}
FUNCTIONS
VIEWS
WRITER
  FileView {
    path: CONTROL
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var command = JSON.parse(text() || "null")
      if (!command) return
      if (command.snapshotPath) historySelectionFile.path = command.snapshotPath
      root.recordPlayed(command.uuid)
      console.log("QUEUED_HISTORY", JSON.stringify(root.pendingRecentRequest),
                  JSON.stringify(historyProcess.command), historySelectionFile.path)
    }
  }
  Component.onCompleted: recordPlayed(FIRST)
}
'''.replace("RUNTIME", json.dumps(str(runtime)))
       .replace("STATE", json.dumps(str(project / "radio-state")))
       .replace("CONTROL", json.dumps(str(control))).replace("FIRST", json.dumps(first["uuid"]))
       .replace("FUNCTIONS", functions).replace("VIEWS", views).replace("WRITER", writer))
    environment = dict(os.environ, XDG_RUNTIME_DIR=str(directory / "runtime"),
                       XDG_DATA_HOME=str(directory / "data"), XDG_CACHE_HOME=str(directory / "cache"),
                       PATH=f"{binary}:{os.environ['PATH']}", RADIO_ATLAS_TEST_LOCK_READY=str(marker),
                       QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_NO_XDG_DESKTOP_PORTAL="1", QT_QPA_PLATFORMTHEME="",
                       QT_QUICK_CONTROLS_STYLE="Basic")
    environment.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
    log_path = directory / "history.log"
    with (state_dir / "state.lock").open("a") as lock, log_path.open("w") as log:
        fcntl.flock(lock, fcntl.LOCK_EX)
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
                raise AssertionError(f"History queue did not finish: {state.read_text()}\n{log_path.read_text()}")

            try:
                wait_for(marker.exists)
                playlist.write_text(json.dumps([queued]))
                update = directory / "control.tmp"
                update.write_text(json.dumps(dict(uuid=queued["uuid"])))
                update.replace(control)
                wait_for(lambda: "QUEUED_HISTORY" in log_path.read_text())
                playlist.write_text(json.dumps([following]))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
            wait_for(lambda: json.loads(state.read_text())["recent"] == [queued, first])
            saved = json.loads(state.read_text())
            assert saved["favorites"] == [following], saved
            assert saved["volume"] == 23, saved

            # A failed snapshot must leave the fallback pending without showing an error.
            updated = dict(queued, name="Updated queued station", url="https://example.com/updated")
            playlist.write_text(json.dumps([updated]))
            blocked = directory / "blocked"
            blocked.write_text("Not a directory")
            marker.unlink()
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                update.write_text(json.dumps(dict(uuid=queued["uuid"],
                                                 snapshotPath=str(blocked / "snapshot.json"))))
                update.replace(control)
                wait_for(marker.exists)
                assert "LOCAL_ERROR Listening history" not in log_path.read_text(), log_path.read_text()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
            wait_for(lambda: json.loads(state.read_text())["recent"] == [updated, first])
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
print("Native history queue test passed")
