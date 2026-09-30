import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)

const stations = ["playing", "browsing", "next"].map(uuid => ({ uuid, name: uuid }))
let visibleIndex = -1
const context = vm.createContext({
  RadioModel: model,
  displayStations: stations,
  playingStationUuid: "",
  recordedStationUuid: "",
  pendingVolume: -1,
  playerError: "",
  ListView: { Contain: 0 },
  stationList: {
    currentIndex: -1,
    positionViewAtIndex(index) { visibleIndex = index },
  },
  highlightStationCountry() {},
  recordPlayed() {},
})
vm.runInContext(source.match(/  function (?:applyPlayerState|setSelection)\([\s\S]*?\n  \}/g).join("\n"), context)

const playing = { running: true, loaded: true, station: stations[0], volume: 70 }
context.applyPlayerState(JSON.stringify(playing))
context.setSelection(1, true)

for (const update of [{ title: "New track" }, { volume: 75 }, { paused: true }]) {
  context.applyPlayerState(JSON.stringify({ ...playing, ...update }))
  assert.equal(context.playerError, "")
  assert.equal(context.selectedStation.uuid, "browsing")
  assert.equal(context.selectedIndex, 1)
  assert.equal(context.stationList.currentIndex, 1)
  assert.equal(visibleIndex, 1)
  assert.equal(context.keyboardSelectionVisible, true)
}

context.applyPlayerState(JSON.stringify({ ...playing, station: stations[2] }))
assert.equal(context.playerError, "")
assert.equal(context.selectedStation.uuid, "next")
assert.equal(context.selectedIndex, 2)
assert.equal(context.stationList.currentIndex, 2)
assert.equal(visibleIndex, 2)

const refreshFunctions = source.match(/  function (?:setSelection|setStationList|moveSelection|playSelected|playlistScope)\([\s\S]*?\n  \}/g).join("\n")
const complete = source.match(/id: fetchProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]

function refreshSession(mode) {
  const rows = [{ uuid: "first", name: "Jazz First" }, { uuid: "chosen", name: "Jazz Chosen" }]
  let played
  const run = vm.createContext({
    RadioModel: model, mode, results: rows, worldStations: rows, worldStationLimit: 5000,
    fetchAction: mode, fetchValue: mode === "search" ? "jazz" : "", pendingFetchAction: "",
    fetchOutput: "", fetching: true, searchField: { text: "jazz" },
    selectedIndex: -1, selectedStation: null, keyboardSelectionVisible: false,
    ListView: { Contain: 0 },
    stationList: { currentIndex: -1, positionViewAtIndex() {} },
    scheduleWorldExpansion() {},
    playStation(station) { played = station.uuid },
  })
  run.root = run
  Object.defineProperty(run, "displayStations", { get() { return run.results } })
  vm.runInContext(`${refreshFunctions}\nfunction complete(exitCode) {${complete}}`, run)
  run.setSelection(0)
  run.moveSelection(1)
  return {
    run, rows,
    finish(nextRows) {
      run.fetchOutput = JSON.stringify(nextRows)
      run.complete(0)
    },
    enter() { run.playSelected(); return played },
  }
}

for (const mode of ["search", "world"]) {
  const session = refreshSession(mode)
  session.finish(session.rows)
  assert.equal(session.run.selectedStation.uuid, "chosen", `${mode} refresh keeps the chosen station`)
  assert.equal(session.run.keyboardSelectionVisible, true)
  assert.equal(session.enter(), "chosen", "Enter still plays the user's choice")

  const updated = { uuid: "chosen", name: "Updated Jazz", url: "https://example.com/new" }
  session.finish([updated, session.rows[0]])
  assert.equal(session.run.selectedStation.uuid, "chosen", "Selection follows UUID through reordering")
  assert.equal(session.run.selectedStation.name, updated.name)
  assert.equal(session.run.selectedStation.url, updated.url)
  assert.equal(session.run.stationList.currentIndex, session.run.selectedIndex)
}

const removed = refreshSession("search")
removed.finish([removed.rows[0]])
assert.equal(removed.run.selectedStation.uuid, "first", "Removed selections fall back to the first result")
removed.finish([])
assert.equal(removed.run.selectedStation, null)
assert.equal(removed.run.selectedIndex, -1)

const newQuery = refreshSession("search")
newQuery.run.setStationList("search", newQuery.rows)
assert.equal(newQuery.run.selectedStation.uuid, "first", "A new query starts a new selection")
assert.equal(newQuery.run.keyboardSelectionVisible, false)
console.log("Station selection tests passed, including search/world refresh and Enter playback")
