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
console.log("Station selection tests passed")
