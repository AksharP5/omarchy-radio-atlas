import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)

const functions = source.match(
  /  function (?:setSelection|setStationList|browseCountry|browseState|clearSubdivision|applyStateStations)\([\s\S]*?\n  \}/g
).join("\n")

function session() {
  const rows = []
  for (let i = 0; i < 200; i++)
    rows.push({ uuid: `ca-${i}`, name: `California ${i}`, countryCode: "US", state: "California" })
  for (let i = 0; i < 10; i++)
    rows.push({ uuid: `tx-${i}`, name: `Texas ${i}`, countryCode: "US", state: "Texas" })
  rows.push({ uuid: "gb-1", name: "United Kingdom 1", countryCode: "GB" })

  const calls = { fetch: [], focusCountry: [], focusSubdivision: [] }
  const context = vm.createContext({
    RadioModel: model,
    mode: "world",
    worldStations: rows,
    worldStationLimit: 5000,
    results: rows,
    selectedStation: null,
    selectedIndex: -1,
    keyboardSelectionVisible: false,
    activeSubdivisionName: "",
    browsedCountryCode: "GB",
    activeCountryCode: "US",
    activeCountryName: "United Kingdom",
    countryCacheLoaded: true,
    countries: [],
    subdivisions: [],
    ListView: { Contain: 0 },
    stationList: { currentIndex: -1, positionViewAtIndex() {} },
    searchField: { text: "" },
    searchDebounce: { stop() {} },
    cancelPendingFetch() {},
    startFetch(action, value) { calls.fetch.push([action, value]) },
    loadSubdivisions() {},
    highlightStationCountry() {},
    keyCatcher: { forceActiveFocus() {} },
    globe: {
      focusCountry(code) { calls.focusCountry.push(code) },
      focusSubdivision(name) { calls.focusSubdivision.push(name) },
    },
  })
  Object.defineProperty(context, "displayStations", { get() { return context.results } })
  context.root = context
  vm.runInContext(functions, context)
  return { context, calls, rows }
}

// A state click from World/Favorites must establish US country browsing first
// and request that state's stations directly.
{
  const { context, calls } = session()
  context.browseState("CALIFORNIA")
  assert.equal(context.mode, "country")
  assert.equal(context.browsedCountryCode, "US", "State browsing must set the browsed country")
  assert.equal(context.activeCountryName, "United States of America")
  assert.equal(context.searchField.text, "United States of America")
  assert.equal(context.activeSubdivisionName, "CALIFORNIA")
  assert.deepEqual(calls.fetch, [["country", "US"], ["state", "CALIFORNIA"]],
    "State browsing must load the US context and the selected state")
  assert.ok(calls.focusSubdivision.includes("CALIFORNIA"))
  assert.ok(context.results.length > 0)
  assert.ok(context.results.every(station => station.state === "California"))
}

// Clearing a state must restore the full loaded country list, not just 150.
{
  const { context, calls } = session()
  context.browseState("CALIFORNIA")
  assert.equal(context.clearSubdivision(), true)
  assert.equal(context.activeSubdivisionName, "")
  assert.equal(context.mode, "country")
  assert.equal(context.results.length, 210, "Escape must restore every loaded US station")
  assert.ok(context.results.some(station => station.state === "Texas"))
  assert.ok(context.results.every(station => station.countryCode === "US"))
  assert.equal(calls.focusCountry.at(-1), "US")
}

// Already browsing the US: selecting another state only fetches that state.
{
  const { context, calls } = session()
  context.mode = "country"
  context.browsedCountryCode = "US"
  context.browseState("TEXAS")
  assert.deepEqual(calls.fetch, [["state", "TEXAS"]])
  assert.equal(context.activeSubdivisionName, "TEXAS")
  assert.ok(context.results.every(station => station.state === "Texas"))
}

// Remote state results replace the preview but keep local-only rows, and are
// filtered to the exact state so substring matches such as Arkansas/Kansas
// cannot leak in.
{
  const { context } = session()
  context.mode = "country"
  context.browsedCountryCode = "US"
  context.browseState("KANSAS")
  const local = [{ uuid: "ks-local", name: "Local Kansas", countryCode: "US", state: "Kansas" }]
  context.results = local
  context.selectedStation = local[0]
  context.selectedIndex = 0
  context.keyboardSelectionVisible = true
  const remote = [
    { uuid: "ks-remote", name: "Remote Kansas", countryCode: "US", state: "Kansas" },
    { uuid: "ar-remote", name: "Arkansas leak", countryCode: "US", state: "Arkansas" },
    { uuid: "mo-remote", name: "Kansas City Missouri", countryCode: "US", state: "Kansas City, Missouri" },
  ]
  context.applyStateStations("KANSAS", remote)
  assert.deepEqual(Array.from(context.results, station => station.uuid),
    ["ks-remote", "ks-local"], "Remote rows stay first and local-only rows are kept")
  assert.equal(context.selectedStation.uuid, "ks-local", "Selection follows the user's station")
  assert.equal(context.keyboardSelectionVisible, true)
  assert.ok(context.worldStations.some(station => station.uuid === "ks-remote"))
  assert.ok(!context.worldStations.some(station => station.uuid === "ar-remote"),
    "Substring state matches must not enter the station cache")
}

// A stale state response is ignored after the user selects another state.
{
  const { context } = session()
  context.mode = "country"
  context.browsedCountryCode = "US"
  context.activeSubdivisionName = "TEXAS"
  const before = context.results
  context.applyStateStations("CALIFORNIA", [
    { uuid: "ca-remote", name: "Late California", countryCode: "US", state: "California" },
  ])
  assert.equal(context.results, before, "A late state response cannot replace another state")
}

// Without a selected state, Escape falls through to closing the panel.
{
  const { context, calls } = session()
  context.mode = "country"
  context.browsedCountryCode = "US"
  const before = context.results
  assert.equal(context.clearSubdivision(), false)
  assert.equal(context.results, before)
  assert.deepEqual(calls.focusCountry, [])
}

// A stale state outside country mode is cleared without restoring a list.
{
  const { context, calls } = session()
  context.mode = "favorites"
  context.activeSubdivisionName = "CALIFORNIA"
  const before = context.results
  assert.equal(context.clearSubdivision(), true)
  assert.equal(context.activeSubdivisionName, "")
  assert.equal(context.results, before)
  assert.deepEqual(calls.focusCountry, [])
}

console.log("State filter tests passed")
