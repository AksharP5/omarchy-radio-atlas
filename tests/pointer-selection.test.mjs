import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const declaration = /\bListView\s*\{\s*id\s*:\s*stationList\b/.exec(source)
assert.ok(declaration, "Could not find the production station list")
const opening = source.indexOf("{", declaration.index)
let depth = 0
let closing = -1
// Ignore braces inside QML strings and comments while finding the object's end.
const tokens = /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\*[\s\S]*?\*\/|\/\/[^\n]*|[{}]/g
for (const token of source.slice(opening).matchAll(tokens)) {
  if (token[0] === "{") depth++
  if (token[0] === "}" && --depth === 0) {
    closing = opening + token.index + 1
    break
  }
}
assert.ok(closing > opening, "Could not find the end of the production station list")
const list = source.slice(declaration.index, closing)
const outputScrim = source.match(/          MouseArea \{\n            visible: root.outputMenuOpen[\s\S]*?\n          \}/)?.[0]
assert.ok(outputScrim, "Could not find the production output menu scrim")
// Count requests at the production ListView boundary without replacing its behavior.
const selectionFunctions = source.match(/  function (?:setSelection|moveSelection)\([\s\S]*?\n  \}/g).join("\n")
  .replace("stationList.positionViewAtIndex(", "viewPositionRequests++\n    stationList.positionViewAtIndex(")
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
assert.ok(fs.existsSync(path.join(shellDirectory, "Ui/Button.qml")),
  "Set OMARCHY_SHELL_DIR to an Omarchy checkout’s shell directory")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-pointer-selection-"))

try {
  // Keep the production list, selection and shell UI; isolate only shell IO.
  fs.symlinkSync(path.resolve(shellDirectory), path.join(directory, "qs"))
  fs.symlinkSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"))
  fs.symlinkSync(fileURLToPath(new URL("../RadioModel.js", import.meta.url)),
    path.join(directory, "RadioModel.js"))
  fs.writeFileSync(path.join(directory, "tst_pointer_selection.qml"), `
import QtQuick
import QtQuick.Controls as QQC
import QtTest
import qs.Ui
import qs.Commons
import "RadioModel.js" as RadioModel

TestCase {
  id: root
  name: "PointerSelection"
  width: 312
  height: 256
  visible: true
  when: windowShown
  property var displayStations: []
  property int selectedIndex: -1
  property var selectedStation: null
  property bool keyboardSelectionVisible: false
  property string playingStationUuid: ""
  property bool outputMenuOpen: false
  property bool fetching: false
  property bool remoteMode: true
  property string fetchError: ""
  property string localError: ""
  property color foreground: "white"
  property color accent: "cyan"
  property color faint: "#333333"
  property color urgent: "red"
  property color dim: "gray"
  property color favoriteColor: "yellow"
  property int plays: 0
  property int viewPositionRequests: 0
  function isFavorite(uuid) { return false }
  function toggleFavorite(uuid) {}
  function playSelected() { plays++ }
  function emptyStateText() { return "" }
  Item {
    id: keyCatcher
    anchors.fill: parent
    focus: true
    Keys.onPressed: function(event) {
      if (event.key === Qt.Key_Down) {
        root.moveSelection(1)
        event.accepted = true
      }
    }
  }
  Item { id: tabs; height: 0 }
  Item { id: playerPanel; y: 192; height: 64 }
  ${selectionFunctions}
  ${list}
  ${outputScrim}

  function init() {
    outputMenuOpen = false
    mouseMove(root, 300, 230)
    displayStations = Array.from({ length: 20 }, function(_, i) {
      return { uuid: "row-" + i, name: "Station " + (i + 1) }
    })
    setSelection(0)
    stationList.contentY = 0
    plays = 0
    keyCatcher.forceActiveFocus()
    waitForPolish(stationList)
    wait(30)
  }

  function pressDownSixTimes() {
    for (var i = 0; i < 6; i++) {
      keyClick(Qt.Key_Down)
      wait(30)
    }
  }

  function test_keyboardScrolling_data() {
    return [
      { tag: "stationary-pointer", pointerInside: true },
      { tag: "pointer-outside", pointerInside: false }
    ]
  }

  function test_keyboardScrolling(data) {
    if (data.pointerInside) mouseMove(stationList, 50, 30)
    pressDownSixTimes()
    compare(selectedIndex, 6, "Six Down presses must select the seventh station")
    compare(selectedStation.uuid, "row-6")
    compare(keyboardSelectionVisible, true)
    verify(stationList.contentY > 0, "Exercise rows moving under the stationary pointer")
  }

  function test_outputMenuBlocksPointerSelection() {
    keyClick(Qt.Key_Down)
    compare(selectedIndex, 1)
    outputMenuOpen = true
    mouseMove(stationList, 50, 30)
    mouseMove(stationList, 50, 158)
    compare(selectedIndex, 1, "Opening the output menu must block station selection behind its scrim")
    compare(keyboardSelectionVisible, true)

    mouseMove(root, 300, 230)
    mouseClick(root, 300, 230)
    compare(outputMenuOpen, false)
    mouseMove(stationList, 50, 158)
    tryCompare(root, "selectedIndex", 2)
    compare(keyboardSelectionVisible, false)
    compare(plays, 0)
  }

  function test_keyboardOutputMenuTogglePreservesStationaryPointerSelection() {
    mouseMove(stationList, 50, 30)
    keyClick(Qt.Key_Down)
    compare(selectedIndex, 1)
    compare(keyboardSelectionVisible, true)
    outputMenuOpen = true
    wait(30)
    outputMenuOpen = false
    wait(30)
    compare(selectedIndex, 1, "Closing the output menu must not treat a stationary pointer as movement")
    compare(keyboardSelectionVisible, true)
    mouseMove(stationList, 51, 30)
    tryCompare(root, "selectedIndex", 0)
    compare(keyboardSelectionVisible, false)
  }

  function test_pointerMovementWithinSelectedRowDoesNotReposition() {
    mouseMove(stationList, 50, 30)
    var requests = viewPositionRequests
    mouseMove(stationList, 51, 30)
    mouseMove(stationList, 52, 30)
    compare(viewPositionRequests, requests, "Moving within the selected row must not reposition the view")

    keyClick(Qt.Key_Down)
    compare(selectedIndex, 1)
    compare(keyboardSelectionVisible, true)
    requests = viewPositionRequests
    mouseMove(stationList, 50, 94)
    compare(selectedIndex, 1)
    compare(keyboardSelectionVisible, false, "Pointer movement still takes over the keyboard-selected row")
    compare(viewPositionRequests, requests + 1)
    mouseMove(stationList, 51, 94)
    compare(viewPositionRequests, requests + 1)
  }

  function test_pointerMovementAndClicksTakeOver() {
    mouseMove(stationList, 50, 30)
    pressDownSixTimes()
    var firstVisible = stationList.indexAt(50, stationList.contentY + 30)
    mouseMove(stationList, 51, 30)
    tryCompare(root, "selectedIndex", firstVisible)
    compare(keyboardSelectionVisible, false)
    mouseMove(stationList, 50, 94)
    tryCompare(root, "selectedIndex", firstVisible + 1)
    keyClick(Qt.Key_Down)
    compare(keyboardSelectionVisible, true)
    mouseClick(stationList, 50, 30)
    compare(selectedIndex, firstVisible)
    compare(plays, 1)
    verify(keyCatcher.activeFocus)
  }

  function test_pointerReentryAtTheSamePosition() {
    mouseMove(stationList, 50, 30)
    pressDownSixTimes()
    var firstVisible = stationList.indexAt(50, stationList.contentY + 30)
    mouseMove(root, 300, 230)
    mouseMove(stationList, 50, 30)
    tryCompare(root, "selectedIndex", firstVisible)
    compare(keyboardSelectionVisible, false)
  }

  function test_favoriteHoverDoesNotSelectStation() {
    mouseMove(stationList, 50, 30)
    keyClick(Qt.Key_Down)
    mouseMove(stationList, stationList.width - 20, 30)
    compare(selectedIndex, 1)
    compare(keyboardSelectionVisible, true)
    mouseMove(stationList, 50, 30)
    tryCompare(root, "selectedIndex", 0)
    compare(keyboardSelectionVisible, false)
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner",
    ["-platform", "offscreen", "-import", directory, "-input", directory], {
      env: { ...process.env, QT_QUICK_BACKEND: "software" },
      stdio: "inherit",
    })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Pointer selection tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
