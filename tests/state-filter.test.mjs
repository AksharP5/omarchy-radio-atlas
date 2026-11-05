import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)

const functions = source.match(
  /  function (?:setSelection|setStationList|browseCountry|browseState|clearSubdivision)\([\s\S]*?\n  \}/g
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

// A state click from World/Favorites must establish US country browsing first.
{
  const { context, calls } = session()
  context.browseState("CALIFORNIA")
  assert.equal(context.mode, "country")
  assert.equal(context.browsedCountryCode, "US", "State browsing must set the browsed country")
  assert.equal(context.activeCountryName, "United States of America")
  assert.equal(context.searchField.text, "United States of America")
  assert.equal(context.activeSubdivisionName, "CALIFORNIA")
  assert.deepEqual(calls.fetch, [["country", "US"]], "State browsing must start a US country fetch")
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

// Already browsing the US: selecting another state must not refetch.
{
  const { context, calls } = session()
  context.mode = "country"
  context.browsedCountryCode = "US"
  context.browseState("TEXAS")
  assert.deepEqual(calls.fetch, [])
  assert.equal(context.activeSubdivisionName, "TEXAS")
  assert.ok(context.results.every(station => station.state === "Texas"))
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
