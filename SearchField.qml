import QtQuick
import QtQuick.Templates as T
import Quickshell.Io
import qs.Commons
import qs.Ui

// TextArea checks clipboard formats without fetching their contents. TextInput
// fetches text on clipboard changes in Qt 6.10, before maximumLength can apply.
T.TextArea {
  id: root

  property color foreground: Color.foreground
  property color accent: Color.accent
  property int maximumLength: 128
  property int editRevision: 0
  property real horizontalOffset: 0
  readonly property real contentInset: Style.spacing.controlPaddingX + Border.left(borderSpec)
  readonly property var borderSpec: Border.controlSpec(activeFocus ? "focus" : hovered ? "hover-cursor" : "normal", foreground, accent)
  signal accepted()

  textFormat: TextEdit.PlainText
  wrapMode: TextEdit.NoWrap
  selectByMouse: true
  activeFocusOnTab: true
  clip: true
  implicitWidth: 200
  implicitHeight: Math.max(font.pixelSize, contentHeight) + topPadding + bottomPadding
  font.family: Style.font.family
  font.pixelSize: Style.font.body
  color: foreground
  selectionColor: Style.selectionFillFor(foreground, accent)
  selectedTextColor: foreground
  leftPadding: contentInset - horizontalOffset
  rightPadding: Style.spacing.controlPaddingX + Border.right(borderSpec) + horizontalOffset
  topPadding: Style.spacing.inputPaddingY + Border.top(borderSpec)
  bottomPadding: Style.spacing.inputPaddingY + Border.bottom(borderSpec)

  onCursorRectangleChanged: {
    if (cursorRectangle.x < contentInset)
      horizontalOffset = Math.max(0, horizontalOffset + cursorRectangle.x - contentInset)
    else if (cursorRectangle.x > width - contentInset)
      horizontalOffset += cursorRectangle.x - width + contentInset
  }

  onTextChanged: {
    editRevision++
    // IME commits are native edits too; reject overflow without trimming the query.
    if (text.length > maximumLength && canUndo) {
      undo()
      return
    }
    var bounded = text.replace(/[\r\n\t\u2028\u2029]/g, " ").slice(0, maximumLength)
    if (text !== bounded) {
      var position = cursorPosition
      text = bounded
      cursorPosition = Math.min(position, text.length)
    }
  }

  function requestPaste(primary) {
    if (pasteProcess.running) return
    pasteProcess.revision = editRevision
    pasteProcess.start = selectionStart
    pasteProcess.end = selectionEnd
    pasteProcess.output = ""
    pasteProcess.command = [decodeURIComponent(Qt.resolvedUrl("radio-clipboard").toString().replace(/^file:\/\//, ""))]
    if (primary) pasteProcess.command = pasteProcess.command.concat(["--primary"])
    pasteProcess.running = true
  }

  Keys.onPressed: function(event) {
    if (event.matches(StandardKey.Paste)) {
      root.requestPaste(false)
      event.accepted = true
      return
    }
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      if (!inputMethodComposing) root.accepted()
      event.accepted = !inputMethodComposing
      return
    }
    if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
      var forward = event.key !== Qt.Key_Backtab && !(event.modifiers & Qt.ShiftModifier)
      nextItemInFocusChain(forward).forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
      event.accepted = true
      return
    }
    // Reject keystrokes before they enter Qt's coalesced undo history.
    var shortcut = (event.modifiers & Qt.ControlModifier) && !(event.modifiers & Qt.AltModifier)
    var insertsText = /[^\x00-\x1f\x7f]/.test(event.text)
    var remaining = maximumLength - length + selectionEnd - selectionStart
    if (!shortcut && insertsText && event.text.length > remaining)
      event.accepted = true
  }

  background: BorderSurface {
    color: Style.controlFill(root.activeFocus, root.hovered, root.foreground, root.accent)
    borderSpec: root.borderSpec
    radius: Style.cornerRadius
  }

  Text {
    x: root.contentInset
    y: root.topPadding
    width: root.availableWidth
    text: root.placeholderText
    textFormat: Text.PlainText
    font: root.font
    color: Qt.darker(root.foreground, 1.6)
    elide: Text.ElideRight
    visible: !root.length && !root.preeditText
  }

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.MiddleButton | Qt.RightButton
    onPressed: function(mouse) {
      root.forceActiveFocus()
      if (mouse.button === Qt.MiddleButton) {
        root.cursorPosition = root.positionAt(mouse.x, mouse.y)
        root.requestPaste(true)
      }
    }
  }

  DropArea {
    anchors.fill: parent
    onEntered: function(drag) { drag.accepted = false }
  }

  RadioProcess {
    id: pasteProcess
    property int revision: -1
    property int start: 0
    property int end: 0
    property string output: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: pasteProcess.output = text
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 || revision !== root.editRevision || !root.activeFocus
          || start !== root.selectionStart || end !== root.selectionEnd) return
      var value = output.replace(/[\r\n\t\u2028\u2029]/g, " ")
      var remaining = root.maximumLength - root.length + end - start
      value = value.slice(0, Math.max(0, remaining))
      root.remove(start, end)
      root.insert(start, value)
      root.cursorPosition = start + value.length
      root.textEdited()
    }
  }
}
