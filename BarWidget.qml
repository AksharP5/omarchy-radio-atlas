import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root

  moduleName: "akshar.radio-atlas"

  property bool playerRunning: false
  property bool playerPaused: false
  property bool playerMuted: false
  property int playerVolume: 70
  property int reportedVolume: 70
  property int pendingVolume: -1
  property string playerTitle: ""
  readonly property string playerPath: Qt.resolvedUrl("radio-player").toString().replace(/^file:\/\//, "")
  readonly property string statusPath: Quickshell.env("XDG_RUNTIME_DIR") + "/omarchy-radio-atlas/status.json"

  function applyPlayerState(raw) {
    try {
      var state = JSON.parse(raw || "{}")
      root.playerRunning = state.running === true
      root.playerPaused = state.paused === true
      root.playerMuted = state.muted === true
      root.reportedVolume = Math.round(Number(state.volume === undefined ? 70 : state.volume))
      if (root.pendingVolume < 0) root.playerVolume = root.reportedVolume
      root.playerTitle = String(state.title || (state.station && state.station.name) || "")
    } catch (error) {
      return
    }
  }

  function runPlayerAction(action) {
    if (actionProcess.running) return
    actionProcess.command = [root.playerPath, action]
    actionProcess.running = true
  }

  function changeVolume(delta) {
    var current = pendingVolume >= 0 ? pendingVolume : playerVolume
    pendingVolume = Math.max(0, Math.min(100, current + (delta > 0 ? 5 : -5)))
    playerVolume = pendingVolume
    flushVolume()
  }

  function flushVolume() {
    if (volumeProcess.running || pendingVolume < 0) return
    volumeProcess.submittedVolume = pendingVolume
    volumeProcess.command = [playerPath, "volume", String(pendingVolume)]
    volumeProcess.running = true
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  FileView {
    path: root.statusPath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.applyPlayerState(text())
    onFileChanged: reload()
  }

  Process {
    id: actionProcess
    command: []
  }

  Process {
    id: volumeProcess
    property int submittedVolume: -1
    command: []
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.pendingVolume = -1
        root.playerVolume = root.reportedVolume
        return
      }

      root.reportedVolume = submittedVolume
      if (root.pendingVolume === submittedVolume) {
        root.pendingVolume = -1
        root.playerVolume = submittedVolume
        return
      }
      Qt.callLater(root.flushVolume)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf0ac"
    active: root.playerRunning && !root.playerPaused
    tooltipText: root.playerRunning
      ? (root.playerPaused ? "Radio paused: " : "Playing: ") + root.playerTitle
        + "  ·  " + (root.playerMuted ? "muted" : root.playerVolume + "%")
      : "Open Radio Atlas"

    onPressed: function(mouseButton) {
      if (!root.bar) return
      if (mouseButton === Qt.RightButton) {
        root.runPlayerAction("stop")
        return
      }
      if (mouseButton === Qt.MiddleButton) {
        root.bar.run("omarchy-shell shell summon akshar.radio-atlas '{\"action\":\"random\"}'")
        return
      }
      root.bar.run("omarchy-shell shell toggle akshar.radio-atlas")
    }

    onWheelMoved: function(delta) {
      root.changeVolume(delta)
    }
  }
}
