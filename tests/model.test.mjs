import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import vm from "node:vm"
import { fileURLToPath } from "node:url"

const testDir = path.dirname(fileURLToPath(import.meta.url))
const source = fs.readFileSync(path.join(testDir, "..", "RadioModel.js"), "utf8")
const model = { Math, Number, Array, String, isFinite }
vm.createContext(model)
vm.runInContext(source, model)

assert.equal(model.clamp(12, 0, 10), 10)
assert.equal(model.wrapLongitude(190), -170)
assert.equal(model.wrapLongitude(-190), 170)

const centre = model.project(0, 0, 0, 0)
assert.ok(Math.abs(centre.x) < 1e-9)
assert.ok(Math.abs(centre.y) < 1e-9)
assert.ok(centre.z > 0.999)

const restored = model.unproject(0.25, -0.2, 20, -30)
const projected = model.project(restored.latitude, restored.longitude, 20, -30)
assert.ok(Math.abs(projected.x - 0.25) < 1e-9)
assert.ok(Math.abs(projected.y + 0.2) < 1e-9)

const square = [[[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]]]
assert.equal(model.pointInPolygon(0, 0, square), true)
assert.equal(model.pointInPolygon(20, 0, square), false)

const countries = JSON.parse(fs.readFileSync(path.join(testDir, "..", "assets", "countries.json"), "utf8")).features
const india = model.countryCentre(countries, "IN")
assert.ok(india.latitude > 5 && india.latitude < 35)
assert.ok(india.longitude > 65 && india.longitude < 100)
const unitedStates = model.countryCentre(countries, "US")
assert.ok(unitedStates.latitude > 25 && unitedStates.latitude < 55)
assert.ok(unitedStates.longitude > -125 && unitedStates.longitude < -65)
const canada = model.countryCentre(countries, "CA")
assert.ok(canada.latitude > 40 && canada.latitude < 65)
assert.ok(canada.longitude > -140 && canada.longitude < -50)
assert.equal(model.countryCentre(countries, "XX"), null)

const stations = [
  { uuid: "a", latitude: 0, longitude: 0 },
  { uuid: "b", latitude: 0, longitude: 180 }
]
assert.equal(model.stationAt(stations, 100, 100, 200, 200, 1, 0, 0, 12).uuid, "a")
assert.equal(model.compactTags("jazz, soul, jazz", 2), "jazz · soul")

const worldStations = [
  { uuid: "world", name: "World", latitude: 1, longitude: 1 },
  { uuid: "shared", name: "Old metadata", latitude: 2, longitude: 2 }
]
const filteredStations = [
  { uuid: "shared", name: "Fresh metadata", latitude: 2, longitude: 2 },
  { uuid: "country", name: "Country", latitude: 3, longitude: 3 }
]
const mergedStations = model.mergeGeoStations(worldStations, filteredStations)
assert.deepEqual(Array.from(mergedStations, station => station.uuid), ["world", "shared", "country"])
assert.equal(mergedStations[1].name, "Fresh metadata")

const mergedCountryStations = model.mergeStations(
  [{ uuid: "cached", name: "Cached" }, { uuid: "shared", name: "Old" }],
  [{ uuid: "shared", name: "Fresh" }, { uuid: "remote", name: "Remote" }],
  3
)
assert.deepEqual(
  Array.from(mergedCountryStations, station => station.uuid),
  ["cached", "shared", "remote"]
)
assert.equal(mergedCountryStations[1].name, "Fresh")

const fullCountryCache = Array.from({ length: 150 }, (_, index) => ({
  uuid: `country-cache-${index}`
}))
const fullCountryRefresh = Array.from({ length: 25 }, (_, index) => ({
  uuid: `country-refresh-${index}`
}))
assert.equal(model.mergeStations(fullCountryCache, fullCountryRefresh, 500).length, 175)

const fullAtlas = Array.from({ length: 5000 }, (_, index) => ({
  uuid: `atlas-${index}`,
  name: `Background ${index}`
}))
const discoveredStations = [
  { uuid: "country-new", name: "Newly discovered" },
  { uuid: "atlas-4999", name: "Fresh country metadata" }
]
const prioritizedAtlas = model.prioritizeStations(discoveredStations, fullAtlas, 5000)
assert.equal(prioritizedAtlas.length, 5000)
assert.deepEqual(
  Array.from(prioritizedAtlas.slice(0, 2), station => station.uuid),
  ["country-new", "atlas-4999"]
)
assert.equal(prioritizedAtlas[1].name, "Fresh country metadata")
assert.equal(prioritizedAtlas.some(station => station.uuid === "atlas-4998"), false)
const reprioritizedAtlas = model.prioritizeStations(
  [{ uuid: "second-country", name: "Second country" }], prioritizedAtlas, 5000
)
assert.deepEqual(
  Array.from(reprioritizedAtlas.slice(0, 3), station => station.uuid),
  ["second-country", "country-new", "atlas-4999"]
)

const fullWorld = Array.from({ length: 500 }, (_, index) => ({
  uuid: `world-${index}`,
  latitude: 0,
  longitude: index / 10
}))
const fullFilter = Array.from({ length: 300 }, (_, index) => ({
  uuid: `filter-${index}`,
  latitude: 1,
  longitude: index / 10
}))
const cappedStations = model.mergeGeoStations(fullWorld, fullFilter)
assert.equal(cappedStations.length, 800)
assert.equal(cappedStations.filter(station => station.uuid.startsWith("world-")).length, 500)

const largeWorld = Array.from({ length: 5000 }, (_, index) => ({
  uuid: `large-world-${index}`,
  latitude: 0,
  longitude: 0
}))
const largeFilter = Array.from({ length: 1000 }, (_, index) => ({
  uuid: `large-filter-${index}`,
  latitude: 1,
  longitude: 1
}))
assert.equal(model.mergeGeoStations(largeWorld, largeFilter).length, 5500)

const estimatedCountries = [{
  properties: { code: "ZZ", name: "Testland" },
  geometry: {
    type: "Polygon",
    coordinates: [[[10, 20], [20, 20], [20, 30], [10, 30], [10, 20]]]
  }
}]
const missingLocations = [
  { uuid: "estimate-one", name: "One", countryCode: "ZZ", latitude: null, longitude: null },
  { uuid: "estimate-two", name: "Two", countryCode: "ZZ", latitude: null, longitude: null }
]
const estimatedStations = model.mergeGeoStations([], missingLocations, estimatedCountries)
assert.equal(estimatedStations.length, 2)
assert.equal(estimatedStations.every(station => station.estimatedLocation === true), true)
assert.equal(estimatedStations.every(station => station.latitude >= 20 && station.latitude <= 30), true)
assert.equal(estimatedStations.every(station => station.longitude >= 10 && station.longitude <= 20), true)
assert.notDeepEqual(
  [estimatedStations[0].latitude, estimatedStations[0].longitude],
  [estimatedStations[1].latitude, estimatedStations[1].longitude]
)
assert.deepEqual(
  Array.from(model.mergeGeoStations([], missingLocations, estimatedCountries), station => [station.latitude, station.longitude]),
  Array.from(estimatedStations, station => [station.latitude, station.longitude])
)

const searchableStations = [
  {
    uuid: "jazz",
    name: "Blue Note 93",
    country: "United States",
    countryCode: "US",
    state: "New York",
    language: "English",
    tags: "jazz,soul",
    codec: "AAC"
  },
  {
    uuid: "ambient",
    name: "Night Signals",
    country: "Germany",
    countryCode: "DE",
    state: "Berlin",
    language: "German",
    tags: "ambient,electronic",
    codec: "MP3"
  }
]
assert.deepEqual(Array.from(model.searchStations(searchableStations, "93"), station => station.uuid), ["jazz"])
assert.deepEqual(Array.from(model.searchStations(searchableStations, "germany"), station => station.uuid), ["ambient"])
assert.deepEqual(Array.from(model.searchStations(searchableStations, "SOUL"), station => station.uuid), ["jazz"])
assert.deepEqual(Array.from(model.searchStations(searchableStations, "")), [])
assert.deepEqual(Array.from(model.stationsForCountry(searchableStations, "de"), station => station.uuid), ["ambient"])
assert.equal(model.searchStations(searchableStations, "a", 1).length, 1)

const playlistRows = Array.from({ length: 8 }, (_, index) => ({ uuid: `queue-${index}` }))
assert.deepEqual(
  Array.from(model.stationWindow(playlistRows, "queue-4", 5), station => station.uuid),
  ["queue-2", "queue-3", "queue-4", "queue-5", "queue-6"]
)
assert.deepEqual(
  Array.from(model.stationWindow(playlistRows, "queue-0", 5), station => station.uuid),
  ["queue-6", "queue-7", "queue-0", "queue-1", "queue-2"]
)
assert.deepEqual(Array.from(model.stationWindow(playlistRows, "missing", 5)), [])

console.log("RadioModel tests passed")
