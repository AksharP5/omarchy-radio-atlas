import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import vm from "node:vm"
import { fileURLToPath } from "node:url"

const project = fileURLToPath(new URL("..", import.meta.url))
const countryNames = JSON.parse(fs.readFileSync(path.join(project, "assets/country-search.json")))
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(path.join(project, "RadioModel.js"), "utf8"), model)

const stations = [
  { uuid: "us", name: "Blue Note", country: "The United States Of America", countryCode: "US", tags: "jazz" },
  { uuid: "gb", name: "Night Signals", country: "The United Kingdom Of Great Britain And Northern Ireland", countryCode: "GB", tags: "ambient" },
  { uuid: "name", name: "USA Radio", country: "Germany", countryCode: "DE", tags: "pop" },
  { uuid: "tag", name: "Overseas", country: "Germany", countryCode: "DE", tags: "usa,jazz" },
  { uuid: "mislabelled", name: "Northern Lights", country: "USA", countryCode: "CA", tags: "folk" },
  { uuid: "tr", name: "Ankara", country: "Turkey", countryCode: "TR", tags: "folk" },
  { uuid: "ax", name: "Island Radio", country: "Aland Islands", countryCode: "AX", tags: "folk" },
]
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-search-"))
try {
  const fixture = path.join(directory, "stations.json")
  fs.writeFileSync(fixture, JSON.stringify(stations.map(station => ({
    ...station,
    stationuuid: station.uuid,
    url: `https://example.com/${station.uuid}`,
    countrycode: station.countryCode,
  }))))
  const env = {
    ...process.env,
    PATH: `${path.join(project, "tests/fixtures")}:${process.env.PATH}`,
    XDG_RUNTIME_DIR: path.join(directory, "runtime"),
    XDG_CACHE_HOME: path.join(directory, "cache"),
    RADIO_ATLAS_TEST_SEARCH_STATIONS: fixture,
  }
  const cases = [
    ["USA", ["us", "name", "tag"]],
    [" uk ", ["gb"]],
    ["uS", ["us", "name", "tag"]],
    ["United States of America", ["us"]],
    ["The United States Of America", ["us"]],
    ["United Kingdom", ["gb"]],
    ["Germany", ["name", "tag"]],
    ["TÜRKIYE", ["tr"]],
    ["Aland Islands", ["ax"]],
    ["ax", ["ax"]],
    ["jazz", ["us", "tag"]],
    ["United", ["us", "gb"]],
    ["unknown query", []],
  ]
  for (const [query, expected] of cases) {
    const preview = model.searchStations(stations, query, 150, countryNames)
    assert.deepEqual(Array.from(preview, station => station.uuid).sort(), [...expected].sort(), `preview: ${query}`)
    const result = spawnSync(path.join(project, "radio-fetch"), ["search", query], { env, encoding: "utf8" })
    assert.equal(result.status, 0, `${query}: ${result.stderr}`)
    assert.deepEqual(JSON.parse(result.stdout).map(station => station.uuid).sort(), [...expected].sort(), `remote: ${query}`)
  }

  const features = JSON.parse(fs.readFileSync(path.join(project, "assets/countries.json"))).features
  for (const { properties } of features)
    assert.equal(countryNames[properties.name.toLowerCase()], properties.code)
  for (const [name, code] of Object.entries(countryNames)) {
    assert.equal(name, name.trim().toLowerCase())
    assert.match(code, /^[A-Z]{2}$/)
    assert.equal(countryNames[code.toLowerCase()], code)
  }

  const incompletePlugin = path.join(directory, "plugin")
  fs.mkdirSync(path.join(incompletePlugin, "assets"), { recursive: true })
  for (const file of ["radio-fetch", "manifest.json"])
    fs.copyFileSync(path.join(project, file), path.join(incompletePlugin, file))
  for (const lookup of [undefined, "{invalid json"]) {
    if (lookup !== undefined)
      fs.writeFileSync(path.join(incompletePlugin, "assets/country-search.json"), lookup)
    const result = spawnSync(path.join(incompletePlugin, "radio-fetch"), ["search", "jazz"], { env, encoding: "utf8" })
    assert.equal(result.status, 0, result.stderr)
    assert.deepEqual(JSON.parse(result.stdout).map(station => station.uuid).sort(), ["tag", "us"])
    assert.notEqual(result.stderr, "", "Keep lookup failures visible in diagnostics")
  }
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
console.log("Country search tests passed")
