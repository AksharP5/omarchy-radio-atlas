import QtQuick
import Quickshell.Io

Item {
  id: root
  visible: false

  property var command: []
  property bool running: false
  property real timeoutSeconds: 60
  property var stdout: null
  property var stderr: null
  property int request: 0
  property bool pending: false
  signal exited(int exitCode, int exitStatus)

  function complete(exitCode, exitStatus) {
    if (!pending) return
    pending = false
    running = false
    exited(exitCode, exitStatus)
  }

  onRunningChanged: {
    if (!running) {
      if (worker.running) {
        running = true
        worker.signal(15)
      }
      return
    }
    if (pending) return
    pending = true
    var current = ++request
    worker.command = ["python3", decodeURIComponent(Qt.resolvedUrl("radio-run").toString().replace(/^file:\/\//, "")),
      String(timeoutSeconds)].concat(command)
    worker.running = true
    // Quickshell does not emit exited when a command fails to start.
    Qt.callLater(function() {
      if (root.request === current && root.pending && !worker.running)
        root.complete(127, 0)
    })
  }

  Process {
    id: worker
    stdout: root.stdout
    stderr: root.stderr
    onExited: function(exitCode, exitStatus) { root.complete(exitCode, exitStatus) }
    onRunningChanged: {
      if (running || !root.pending) return
      var current = root.request
      Qt.callLater(function() {
        if (root.request === current && root.pending && !worker.running)
          root.complete(127, 0)
      })
    }
  }
}
