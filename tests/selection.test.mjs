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
  playerRunning: false,
  playerStopped: false,
  localStopStatusPending: false,
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

const refreshFunctions = source.match(/  function (?:setSelection|setStationList|moveSelection|playSelected|playlistScope|previewSearch|search)\([\s\S]*?\n  \}/g).join("\n")
const debounce = source.match(/id: searchDebounce[\s\S]*?onTriggered: ([^\n]+)/)[1]
const complete = source.match(/id: fetchProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]

function refreshSession(mode) {
  const rows = [{ uuid: "first", name: "Jazz First" }, { uuid: "chosen", name: "Jazz Chosen" }]
  let played
  let requestedQuery
  const run = vm.createContext({
    RadioModel: model, mode, results: rows, worldStations: rows, worldStationLimit: 5000,
    fetchAction: mode, fetchValue: mode === "search" ? "jazz" : "", pendingFetchAction: "",
    fetchOutput: "", fetching: true, searchField: { text: "jazz" },
    selectedIndex: -1, selectedStation: null, keyboardSelectionVisible: false,
    ListView: { Contain: 0 },
    stationList: { currentIndex: -1, positionViewAtIndex() {} },
    countryNames: {},
    restorePlayingCountry() {},
    startFetch(action, query) { requestedQuery = query },
    scheduleWorldExpansion() {},
    playStation(station) { played = station.uuid },
    keyCatcher: { forceActiveFocus() {} },
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
    debounce() { vm.runInContext(debounce, run); return requestedQuery },
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

const waiting = refreshSession("search")
waiting.run.previewSearch("jazz")
waiting.run.moveSelection(1)
assert.equal(waiting.debounce(), "jazz")
assert.equal(waiting.run.selectedStation.uuid, "chosen", "Starting the debounced fetch keeps the preview selection")
assert.equal(waiting.run.keyboardSelectionVisible, true)

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

const localFunctions = source.match(/  function (?:applyLocalState|refreshLocalSelection|setSelection|playSelected|playlistScope)\([\s\S]*?\n  \}/g).join("\n")
for (const mode of ["favorites", "recent"]) {
  let played
  const rows = [{ uuid: "first" }, { uuid: "chosen" }]
  const run = vm.createContext({
    RadioModel: model, mode, favorites: rows, recent: rows,
    selectedStation: null, selectedIndex: -1, keyboardSelectionVisible: false,
    playingStationUuid: "first", ListView: { Contain: 0 },
    stationList: { currentIndex: -1, positionViewAtIndex() {} },
    playStation(station, scope) { played = [station.uuid, scope] },
  })
  Object.defineProperty(run, "displayStations", { get: () => run[mode] })
  vm.runInContext(localFunctions, run)
  run.setSelection(1, true)
  const updated = { uuid: "chosen", name: "Updated saved station" }
  run.applyLocalState(JSON.stringify({ favorites: [updated, rows[0]], recent: [updated, rows[0]] }))
  run.refreshLocalSelection()
  assert.equal(run.selectedStation.uuid, "chosen", `${mode} reload follows the chosen station`)
  assert.equal(run.selectedStation.name, updated.name)
  assert.equal(run.selectedIndex, 0)
  assert.equal(run.keyboardSelectionVisible, true, `${mode} reload keeps its keyboard outline`)
  run.playSelected()
  assert.deepEqual(played, ["chosen", mode])

  run[mode] = [rows[0]]
  run.refreshLocalSelection()
  assert.equal(run.selectedStation.uuid, "first", "Removing the selected saved station selects its neighbor")
  assert.equal(run.keyboardSelectionVisible, true)
  run.setSelection(0)
  run.refreshLocalSelection()
  assert.equal(run.keyboardSelectionVisible, false, "Pointer selections do not gain a keyboard outline")
  run[mode] = []
  run.refreshLocalSelection()
  assert.equal(run.selectedStation, null)
  assert.equal(run.selectedIndex, -1)
}

for (const stopped of [{ running: false }, { ...playing, stopped: true }]) {
  context.applyPlayerState(JSON.stringify(playing))
  context.randomPlaybackPending = true
  context.applyPlayerState(JSON.stringify(stopped))
  assert.equal(context.randomPlaybackPending, false,
    "A stop from the bar or media controls cancels pending random playback")
  context.randomPlaybackPending = true
  context.applyPlayerState(JSON.stringify(stopped))
  assert.equal(context.randomPlaybackPending, true,
    "Repeated stopped status must not cancel a new Random request")
}

console.log("Station selection tests passed, including remote/saved refresh and Enter playback")
