import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const sections = source.match(/  readonly property var controlSections: \[[\s\S]*?\n  \]/)[0]
const pane = source.match(/      Flickable \{\n        id: controlsPane[\s\S]*(?=\n    \}\n  \}\n\})/)[0]
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-controls-layout-"))

try {
  fs.symlinkSync(path.resolve(shellDirectory), path.join(directory, "qs"))
  fs.symlinkSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"))
  fs.writeFileSync(path.join(directory, "tst_controls_layout.qml"), `
import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC
import QtTest
import qs.Commons

TestCase {
  id: root
  name: "ControlsLayout"
  visible: true
  when: windowShown
  width: 1068
  height: 672
  property bool helpVisible: true
  property color background: "#101315"
  property color foreground: "#cacccc"
  property color dim: "#707880"
  property color faint: "#333333"
  ${sections}
  Item {
    id: card
    anchors.fill: parent
    property int borderLeft: 1
    property int borderRight: 1
    property int borderBottom: 1
    Item { id: header; width: parent.width; height: Style.space(46) }
    ${pane}
  }

  function test_helpFits_data() {
    return [
      { tag: "laptop", w: 1068, h: 672, font: 12, columns: 2 },
      { tag: "large-font-laptop", w: 1043, h: 639, font: 17, columns: 2 },
      { tag: "below-old-minimum", w: 580, h: 432, font: 12, columns: 1 },
      { tag: "portrait-2x", w: 480, h: 760, font: 12, columns: 1 }
    ]
  }
  function verifyTextPainted(text) {
    var point = text.mapToItem(controlsPane, 0, 0)
    var image = grabImage(controlsPane)
    for (var y = Math.ceil(point.y); y < Math.min(image.height, point.y + text.height); y += 2)
      for (var x = Math.ceil(point.x); x < Math.min(image.width, point.x + text.width); x += 2)
        if (!Qt.colorEqual(image.pixel(x, y), root.background)) return
    fail("Help text must be painted above the background")
  }
  function test_helpFits(data) {
    width = data.w
    height = data.h
    Style.fontBaseSize = data.font
    controlsPane.contentY = 0
    verify(waitForPolish(root.Window.window))
    compare(controlsColumns.columns, data.columns)
    var title = controlsContent.children[0]
    var start = title.mapToItem(controlsPane, 0, 0)
    verify(start.y >= Style.spacing.panelPadding, "The title must stay below the window header")
    verifyTextPainted(title)
    if (controlsPane.contentHeight > controlsPane.height) {
      mouseWheel(controlsPane, width / 2, controlsPane.height / 2, 0, -720)
      tryVerify(function() { return controlsPane.contentY > 0 }, 1000, "Short help pages must scroll")
    }
    controlsPane.contentY = controlsPane.contentHeight - controlsPane.height
    var groups = controlsColumns.children.filter(function(item) { return item.modelData && item.modelData.controls })
    var rows = groups[groups.length - 1].children.filter(function(item) { return item.modelData && item.modelData.action })
    var lastRow = rows[rows.length - 1]
    var bottom = lastRow.mapToItem(controlsPane, 0, lastRow.height)
    verify(bottom.y <= controlsPane.height - Style.spacing.panelPadding + 0.5,
      "The last shortcut must be reachable with its bottom padding")
    verifyTextPainted(lastRow.children[0])
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-import", directory, "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software", QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Controls layout tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
