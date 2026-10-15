import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const header = source.match(/      Item \{\n        id: header[\s\S]*?(?=\n      Item \{\n        id: body)/)?.[0]
assert.ok(header, "Could not find the production header")
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
assert.ok(fs.existsSync(path.join(shellDirectory, "Ui/Button.qml")),
  "Set OMARCHY_SHELL_DIR to an Omarchy checkout’s shell directory")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-header-layout-"))

try {
  fs.symlinkSync(path.resolve(shellDirectory), path.join(directory, "qs"))
  fs.symlinkSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"))
  fs.writeFileSync(path.join(directory, "tst_header_layout.qml"), `
import QtQuick
import QtQuick.Window
import QtTest
import qs.Ui
import qs.Commons

TestCase {
  id: root
  name: "HeaderLayout"
  width: 1180
  height: 200
  visible: true
  when: windowShown
  property color background: "#101315"
  property color foreground: "white"
  property color accent: "cyan"
  property color faint: "gray"
  property bool helpVisible: false
  property int randomRequests: 0
  property int helpRequests: 0
  property int dismissals: 0
  readonly property int edgeInset: Style.spacing.md
  readonly property int headerHeight: Math.ceil(Math.max(searchField.implicitHeight,
    randomButton.implicitHeight, helpButton.implicitHeight, closeButton.implicitHeight))
    + edgeInset * 2
  function previewSearch(text) { return false }
  function search(text) {}
  function tuneRandom() { randomRequests++ }
  function toggleControls() { helpRequests++ }
  function dismiss() { dismissals++ }
  Timer { id: searchDebounce }

  Item {
    id: card
    anchors.fill: parent
    Rectangle { anchors.fill: parent; color: root.background }
    ${header}
  }

  function test_headerFits_data() {
    return [
      { tag: "desktop", w: 1180, font: 12 },
      { tag: "laptop", w: 1068, font: 12 },
      { tag: "small-window", w: 580, font: 12 },
      { tag: "portrait", w: 480, font: 12 },
      { tag: "large-font-laptop", w: 1043, font: 17 },
      // A rotated 2x display leaves 540 logical pixels before font-scaled margins.
      { tag: "large-font-portrait", w: 455, font: 17 },
      { tag: "larger-font-portrait", w: 420, font: 24 }
    ]
  }

  function test_headerFits(data) {
    width = data.w
    Style.fontBaseSize = data.font
    verify(waitForPolish(root.Window.window))
    verify(title.x >= 0 && title.width > 0)
    verify(title.x + title.width <= searchField.x,
      "The window title must not overlap search")
    var controls = [searchField, randomButton, helpButton, closeButton]
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i]
      verify(control.visible && control.width > 0 && control.height > 0,
        "Every header control must remain visible")
      verify(control.x >= 0 && control.x + control.width <= header.width,
        "Header controls must fit horizontally")
      verify(control.y >= 0 && control.y + control.height <= header.height,
        "Header controls must fit vertically")
      if (i > 0)
        verify(controls[i - 1].x + controls[i - 1].width <= control.x,
          "Header controls must not overlap")
    }
    searchField.clear()
    mouseClick(searchField)
    verify(searchField.activeFocus)
    keyClick(Qt.Key_J)
    compare(searchField.text.toLowerCase(), "j")
    randomRequests = 0
    helpRequests = 0
    dismissals = 0
    mouseClick(randomButton)
    mouseClick(helpButton)
    mouseClick(closeButton)
    compare(randomRequests, 1)
    compare(helpRequests, 1)
    compare(dismissals, 1)
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner",
    ["-platform", "offscreen", "-import", directory, "-input", directory], {
      env: { ...process.env, QT_QUICK_BACKEND: "software",
        QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
      stdio: "inherit",
    })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Header layout tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
