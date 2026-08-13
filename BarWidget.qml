import QtQuick
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
  property string playerTitle: ""
  readonly property string playerPath: Qt.resolvedUrl("radio-player").toString().replace(/^file:\/\//, "")

  function refreshStatus() {
    if (!statusProcess.running) statusProcess.running = true
  }

  function runPlayerAction(action) {
    if (actionProcess.running) return
    actionProcess.command = [root.playerPath, action]
    actionProcess.running = true
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: statusProcess
    command: [root.playerPath, "status"]
    property string output: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: statusProcess.output = text
    }
    onExited: {
      try {
        var state = JSON.parse(output || "{}")
        root.playerRunning = state.running === true
        root.playerPaused = state.paused === true
        root.playerMuted = state.muted === true
        root.playerVolume = Math.round(Number(state.volume === undefined ? 70 : state.volume))
        root.playerTitle = String(state.title || "")
      } catch (error) {
        root.playerRunning = false
        root.playerPaused = false
        root.playerMuted = false
        root.playerTitle = ""
      }
    }
  }

  Process {
    id: actionProcess
    command: []
    onExited: root.refreshStatus()
  }

  Timer {
    interval: root.playerRunning ? 3000 : 8000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refreshStatus()
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
      root.runPlayerAction(delta > 0 ? "volume-up" : "volume-down")
    }
  }
}
