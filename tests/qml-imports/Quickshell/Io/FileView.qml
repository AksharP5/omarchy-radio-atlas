import QtQuick

QtObject {
  property string path: ""
  property bool watchChanges: false
  property bool printErrors: false
  signal fileChanged()
  signal loaded()
  signal loadFailed()
  function text() { return "" }
  function reload() {}
}
