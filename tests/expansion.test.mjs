import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const schedule = source.match(/function scheduleWorldExpansion\(delay\) \{([\s\S]*?)\n  \}/)[1]
const complete = source.match(/id: worldExpandProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const open = source.match(/function openWindow\(payloadJson\) \{([\s\S]*?)\n  \}/)[1]
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)

function session() {
  const delays = []
  const context = vm.createContext({
    opened: true,
    worldStationLimit: 5000,
    worldExpansionMisses: 0,
    worldStations: [{ uuid: "first" }],
    mode: "world",
    RadioModel: model,
    panel: {},
    windowRevealTimer: { stop() {} },
    loadState() {},
    setStationList(_mode, rows) { this.results = rows },
    Qt: { callLater() {} },
    worldExpandTimer: { interval: 0, restart() { delays.push(this.interval) } },
  })
  context.root = context
  vm.runInContext(`function scheduleWorldExpansion(delay) {${schedule}}
    function complete(exitCode) {${complete}}
    function openWindow(payloadJson) {${open}}`, context)
  return {
    context,
    delays,
    finish(rows, exitCode = 0) {
      context.worldExpandOutput = JSON.stringify(rows)
      context.complete(exitCode)
    },
  }
}

for (const [rows, exitCode] of [[[ { uuid: "first" } ], 0], [[], 0], [null, 0], [[], 1]]) {
  const run = session()
  const original = run.context.worldStations
  for (let i = 0; i < 3; i++) run.finish(rows, exitCode)
  assert.equal(run.context.worldExpansionMisses, 3)
  assert.equal(run.delays.length, 2)
  assert.equal(run.context.worldStations, original)
  run.context.openWindow("{}")
  assert.equal(run.context.worldExpansionMisses, 0)
  assert.equal(run.delays.at(-1), 800)
}

const run = session()
run.finish([{ uuid: "first" }])
run.finish([{ uuid: "first" }])
run.finish([{ uuid: "second" }])
assert.equal(run.context.worldExpansionMisses, 0)
assert.equal(run.context.worldStations.length, 2)
assert.equal(run.delays.at(-1), 1600)
run.context.opened = false
run.finish([{ uuid: "third" }])
assert.equal(run.context.worldStations.length, 2)
assert.equal(run.delays.length, 3)

const selectionFunctions = source.match(/  function (?:setSelection|setStationList)\([\s\S]*?\n  \}/g).join("\n")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-expansion-"))
try {
  fs.copyFileSync(new URL("../RadioModel.js", import.meta.url), path.join(directory, "RadioModel.js"))
  fs.writeFileSync(path.join(directory, "tst_expansion.qml"), `
import QtQuick
import QtTest
import "RadioModel.js" as RadioModel

TestCase {
  id: root
  width: 300
  height: 200
  visible: true
  when: windowShown
  property bool opened: true
  property string mode: "world"
  property int worldStationLimit: 5000
  property int worldExpansionMisses: 0
  property var worldStations: Array.from({ length: 50 }, function(_, index) {
    return { uuid: String(index), name: "Station " + index }
  })
  property var results: worldStations
  readonly property var displayStations: results
  property string worldExpandOutput: ""
  property int selectedIndex: -1
  property var selectedStation: null
  property bool keyboardSelectionVisible: false
  property string activeSubdivisionName: ""
  function scheduleWorldExpansion(delay) {}
  function highlightStationCountry() {}
  function complete(exitCode) {${complete}}
  ${selectionFunctions}

  ListView {
    id: stationList
    anchors.fill: parent
    model: root.displayStations
    currentIndex: root.selectedIndex
    delegate: Text {
      required property var modelData
      text: modelData.name
      height: 40
    }
  }

  function test_expansionKeepsTheSelectedRowVisible() {
    setSelection(30, true)
    wait(1)
    verify(stationList.contentY > 0)
    worldExpandOutput = JSON.stringify([
      { uuid: "30", name: "Updated station" }, { uuid: "new", name: "New station" }
    ])
    complete(0)
    wait(1)
    compare(stationList.currentIndex, 30)
    compare(selectedStation.uuid, "30")
    compare(selectedStation.name, "Updated station")
    verify(keyboardSelectionVisible)
    var row = stationList.currentItem
    verify(row !== null)
    verify(row.y >= stationList.contentY)
    verify(row.y + row.height <= stationList.contentY + stationList.height)
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software",
      QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "World expansion must preserve native list selection")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
console.log("World expansion tests passed")
