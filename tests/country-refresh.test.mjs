import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import vm from "node:vm"
import { setTimeout } from "node:timers/promises"
import { fileURLToPath } from "node:url"

const project = fileURLToPath(new URL("..", import.meta.url))
const source = fs.readFileSync(path.join(project, "RadioAtlas.qml"), "utf8")
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(path.join(project, "RadioModel.js"), "utf8"), model)
const functions = source.match(/  function (?:setSelection|setStationList|browseCountry|applyCountryStations|applyCountryCache)\([\s\S]*?\n  \}/g).join("\n")
const response = source.match(/else if \(root\.fetchAction === "country"\) \{([\s\S]*?)\n      \} else if/)?.[1]
assert.ok(response)
const loaded = source.match(/onLoaded: root\.applyCountryCache\(text\(\)\)/)?.[0]
assert.ok(loaded, "The active country's cache must feed the open list")

const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-country-refresh-"))
try {
  const cache = path.join(directory, "cache", "omarchy-radio-atlas")
  fs.mkdirSync(cache, { recursive: true })
  const stations = Array.from({ length: 25 }, (_, index) => ({
    uuid: `${String(index).padStart(8, "0")}-1111-1111-1111-aaaaaaaaaaaa`,
    name: `Station ${index + 1}`,
    url: `https://example.com/stream-${index}`,
    countryCode: "US",
    latitude: 40,
    longitude: -74,
  }))
  fs.writeFileSync(path.join(cache, "world.json"), JSON.stringify(stations.slice(0, 1)))
  const payload = path.join(directory, "payload.json")
  fs.writeFileSync(payload, JSON.stringify(stations.map(station => ({
    ...station, stationuuid: station.uuid, countrycode: station.countryCode,
    geo_lat: station.latitude, geo_long: station.longitude,
  }))))
  const result = spawnSync(path.join(project, "radio-fetch"), ["country", "US"], {
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: `${path.join(project, "tests/fixtures")}:${process.env.PATH}`,
      XDG_RUNTIME_DIR: path.join(directory, "runtime"),
      XDG_CACHE_HOME: path.join(directory, "cache"),
      RADIO_ATLAS_TEST_CURL_PAYLOAD: payload,
    },
  })
  assert.equal(result.status, 0, result.stderr)
  const preview = JSON.parse(result.stdout)
  assert.equal(preview.length, 1, "Country browsing retains its immediate cached response")

  const countryCache = path.join(cache, "countries", "US.json")
  for (let attempt = 0; attempt < 100 && !fs.existsSync(countryCache); attempt++)
    await setTimeout(20)
  const raw = fs.readFileSync(countryCache, "utf8")
  assert.equal(JSON.parse(raw).length, 25)
  const warnings = []
  const context = vm.createContext({
    RadioModel: model,
    mode: "country",
    browsedCountryCode: "US",
    countryCacheLoaded: false,
    fetchValue: "US",
    stations: preview,
    worldStations: preview,
    results: preview,
    selectedStation: preview[0],
    keyboardSelectionVisible: true,
    worldStationLimit: 5000,
    countries: [],
    searchDebounce: { stop() {} },
    cancelPendingFetch() {},
    searchField: { text: "United States" },
    startFetch() {},
    keyCatcher: { forceActiveFocus() {} },
    countryCacheFile: { reload() {} },
    stationList: { currentIndex: 0, positionViewAtIndex() {} },
    ListView: { Contain: 0 },
    console: { warn(...args) { warnings.push(args) } },
    text() { return raw },
  })
  Object.defineProperty(context, "displayStations", { get() { return context.results } })
  context.root = context
  vm.runInContext(functions + `\nfunction applyCountryResponse() {${response}}`, context)
  context.applyCountryResponse()
  vm.runInContext(loaded.replace("onLoaded:", ""), context)
  assert.equal(context.results.length, 25, "Background refresh reaches the still-open country list")
  assert.equal(context.worldStations.length, 25)
  assert.equal(context.selectedStation.uuid, preview[0].uuid)
  assert.equal(context.keyboardSelectionVisible, true)

  const updated = { ...stations[0], name: "Updated station", url: "https://example.com/new" }
  context.applyCountryCache(JSON.stringify([updated, ...stations.slice(1)]))
  context.applyCountryResponse()
  assert.equal(context.selectedStation.name, updated.name, "Late cached stdout cannot undo the refresh")
  assert.equal(context.selectedStation.url, updated.url)
  assert.equal(context.worldStations[0].url, updated.url)
  context.browseCountry("US", "United States")
  context.applyCountryResponse()
  assert.equal(context.selectedStation.url, updated.url, "Reopening the same country cannot restore old stdout")

  context.setSelection(7, true)
  context.applyCountryCache(raw)
  assert.equal(context.selectedStation.uuid, stations[7].uuid, "Repeated updates keep the user's selection")
  context.browseCountry("GB", "United Kingdom")
  assert.equal(context.countryCacheLoaded, false)
  const current = context.results
  context.applyCountryCache(raw)
  context.applyCountryStations("US", JSON.parse(raw))
  context.applyCountryResponse()
  assert.equal(context.countryCacheLoaded, false)
  assert.equal(context.results, current, "A late update cannot replace a different country's list")
  context.mode = "search"
  context.browsedCountryCode = "US"
  context.applyCountryCache(raw)
  context.applyCountryStations("US", JSON.parse(raw))
  assert.equal(context.results, current, "A late country update cannot replace search results")

  context.mode = "country"
  for (const invalid of ["{", "{}", "[null]", JSON.stringify([...stations, stations[0]])]) {
    context.applyCountryCache(invalid)
    assert.equal(context.results, current)
  }
  assert.equal(warnings.length, 5)
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
console.log("Country refresh tests passed")
