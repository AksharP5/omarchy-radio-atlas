import QtQuick

QtObject {
  property var command: []
  property bool running: false
  property QtObject stdout
  property QtObject stderr
  signal exited(int exitCode, int exitStatus)
  function signal(signum) {}
}
