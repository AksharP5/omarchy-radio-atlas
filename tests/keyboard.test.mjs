import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
// Preserve the production handler's owner and focus target; omit only the window skin.
const card = source.match(/    BorderSurface \{[\s\S]*?(?=      Item \{\n        id: header)/)[0]
  .replace("BorderSurface {", "Item {")
  .replace(/^      (color|borderSpec|radius):.*\n/gm, "")
const helpFunctions = source.match(/  function (?:isHelpKey|toggleControls)\([\s\S]*?\n  \}/g).join("\n")
const selectionFunctions = source.match(/  function (?:setSelection|moveSelection)\([\s\S]*?\n  \}/g).join("\n")
const tabs = source.match(/          Item \{\n            id: tabs[\s\S]*?(?=\n          ListView \{)/)[0]
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
assert.ok(fs.existsSync(path.join(shellDirectory, "Ui/Button.qml")),
  "Set OMARCHY_SHELL_DIR to an Omarchy checkout’s shell directory")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-keyboard-"))

try {
  fs.symlinkSync(path.resolve(shellDirectory), path.join(directory, "qs"))
  fs.symlinkSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"))
  fs.writeFileSync(path.join(directory, "tst_keyboard.qml"), `
import QtQuick
import QtTest
import qs.Ui
import qs.Commons

TestCase {
  id: root
  name: "Keyboard"
  width: 500
  height: 200
  visible: true
  when: windowShown
  property bool helpVisible: false
  property bool outputMenuOpen: false
  property int dismissals: 0
  property int worldRequests: 0
  property int randomRequests: 0
  property string mode: "world"
  property var displayStations: [{ uuid: "first" }, { uuid: "chosen" }]
  property int selectedIndex: -1
  property var selectedStation: null
  property bool keyboardSelectionVisible: false
  property string playedUuid: ""
  property color foreground: "white"
  property color accent: "cyan"
  property color faint: "gray"
  function dismiss() { dismissals++ }
  function showWorld() { worldRequests++; mode = "world"; setSelection(0) }
  function showFavorites() { mode = "favorites"; setSelection(0) }
  function showRecent() { mode = "recent"; setSelection(0) }
  function playSelected() { playedUuid = selectedStation.uuid }
  function tuneRandom() { randomRequests++ }
  QtObject {
    id: stationList
    property int currentIndex: -1
    function positionViewAtIndex(index, positionMode) {}
  }
  ${helpFunctions}
  ${selectionFunctions}

  ${card}
    Item {
      id: header
      TextInput { id: searchField }
      Item { id: headerButton }
    }
    ${tabs}
  }

  function init() {
    searchField.text = ""
    helpVisible = false
    dismissals = 0
    worldRequests = 0
    randomRequests = 0
    mode = "world"
    playedUuid = ""
    setSelection(0)
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

  function test_tabSwitchesViewsThenArrowsAndEnterPlay() {
    searchField.forceActiveFocus()
    keyClick(Qt.Key_Tab)
    keyClick(Qt.Key_Return)
    compare(worldRequests, 1)
    keyClick(Qt.Key_Tab)
    keyClick(Qt.Key_Space)
    compare(mode, "favorites")
    keyClick(Qt.Key_Tab)
    keyClick(Qt.Key_Enter)
    compare(mode, "recent")
    keyClick(Qt.Key_Tab, Qt.ShiftModifier)
    keyClick(Qt.Key_Return)
    compare(mode, "favorites")
    keyClick(Qt.Key_Down)
    compare(selectedStation.uuid, "chosen")
    verify(keyCatcher.activeFocus, "Arrow navigation must move keyboard control to the station list")
    keyClick(Qt.Key_Return)
    compare(playedUuid, "chosen")
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-import", directory, "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software",
      QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Keyboard interaction tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
