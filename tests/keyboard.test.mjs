import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
// Preserve the production handler's owner and focus target; omit only the window skin.
const card = source.match(/    BorderSurface \{[\s\S]*?(?=      Item \{\n        id: header)/)[0]
  .replace("BorderSurface {", "Item {")
  .replace(/^      (color|borderSpec|radius):.*\n/gm, "")
const helpFunctions = source.match(/  function (?:isHelpKey|toggleControls)\([\s\S]*?\n  \}/g).join("\n")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-keyboard-"))

try {
  fs.writeFileSync(path.join(directory, "tst_keyboard.qml"), `
import QtQuick
import QtTest

TestCase {
  id: root
  name: "Keyboard"
  width: 500
  height: 200
  when: windowShown
  property bool helpVisible: false
  property bool outputMenuOpen: false
  property int dismissals: 0
  property int worldRequests: 0
  property int randomRequests: 0
  function dismiss() { dismissals++ }
  function showWorld() { worldRequests++ }
  function tuneRandom() { randomRequests++ }
  ${helpFunctions}

  ${card}
    Item {
      id: header
      TextInput { id: searchField }
      Item { id: headerButton }
    }
  }

  function init() {
    searchField.text = ""
    helpVisible = false
    dismissals = 0
    worldRequests = 0
    randomRequests = 0
    keyCatcher.forceActiveFocus()
  }

  function test_escapeClearsSearchThenReturnsFocusThenCloses() {
    keyClick(Qt.Key_Slash)
    verify(searchField.activeFocus)
    searchField.text = "jazz"
    keyClick(Qt.Key_Escape)
    compare(searchField.text, "")
    compare(worldRequests, 1)
    verify(searchField.activeFocus)
    keyClick(Qt.Key_Escape)
    verify(keyCatcher.activeFocus)
    compare(dismissals, 0)
    keyClick(Qt.Key_Escape)
    compare(dismissals, 1)
  }

  function test_shortcutsFromOtherControlsDoNotInterceptTyping() {
    headerButton.forceActiveFocus()
    keyClick(Qt.Key_R)
    compare(randomRequests, 1)
    keyClick(Qt.Key_Slash)
    verify(searchField.activeFocus)
    keyClick(Qt.Key_R)
    compare(searchField.text.toLowerCase(), "r")
    compare(randomRequests, 1)
  }

  function test_escapeClosesHelpBeforeWindow() {
    helpVisible = true
    headerButton.forceActiveFocus()
    keyClick(Qt.Key_Escape)
    compare(helpVisible, false)
    compare(dismissals, 0)
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Keyboard interaction tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
