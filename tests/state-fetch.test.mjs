import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const project = fileURLToPath(new URL("..", import.meta.url))
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-state-fetch-"))

try {
  const cache = path.join(directory, "cache", "omarchy-radio-atlas")
  const runtime = path.join(directory, "runtime")
  fs.mkdirSync(cache, { recursive: true })
  fs.mkdirSync(runtime, { recursive: true })

  const payload = path.join(directory, "payload.json")
  fs.writeFileSync(payload, JSON.stringify([
    {
      stationuuid: "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa",
      name: "Los Angeles Jazz",
      url_resolved: "https://example.com/la",
      countrycode: "US",
      state: "California",
      geo_lat: 34.05,
      geo_long: -118.24,
      clickcount: 50,
    },
    {
      stationuuid: "bbbbbbbb-1111-1111-1111-bbbbbbbbbbbb",
      name: "Bay Area Talk",
      url_resolved: "https://example.com/sf",
      countrycode: "US",
      state: "California",
      geo_lat: 37.77,
      geo_long: -122.42,
      clickcount: 40,
    },
    {
      stationuuid: "cccccccc-1111-1111-1111-cccccccccccc",
      name: "Austin Country",
      url_resolved: "https://example.com/austin",
      countrycode: "US",
      state: "Texas",
      geo_lat: 30.27,
      geo_long: -97.74,
      clickcount: 30,
    },
    {
      stationuuid: "dddddddd-1111-1111-1111-dddddddddddd",
      name: "Little Rock Blues",
      url_resolved: "https://example.com/lr",
      countrycode: "US",
      state: "Arkansas",
      geo_lat: 34.75,
      geo_long: -92.29,
      clickcount: 20,
    },
  ]))

  const env = {
    ...process.env,
    PATH: `${path.join(project, "tests/fixtures")}:${process.env.PATH}`,
    XDG_RUNTIME_DIR: runtime,
    XDG_CACHE_HOME: path.join(directory, "cache"),
    RADIO_ATLAS_TEST_CURL_PAYLOAD: payload,
    RADIO_ATLAS_TEST_SEARCH_STATIONS: payload,
  }
  const fetch = (...args) => spawnSync(path.join(project, "radio-fetch"), args, {
    encoding: "utf8",
    env,
  })

  const result = fetch("state", "CALIFORNIA")
  assert.equal(result.status, 0, result.stderr)
  const stations = JSON.parse(result.stdout)
  assert.deepEqual(stations.map(station => station.uuid).sort(),
    ["aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa", "bbbbbbbb-1111-1111-1111-bbbbbbbbbbbb"],
    "State browsing returns only the selected state")
  assert.ok(stations.every(station => station.countryCode === "US"))
  assert.ok(stations.every(station => station.state === "California"))

  const stateCache = path.join(cache, "states", "california.json")
  assert.equal(fs.existsSync(stateCache), true, "State results are cached by slug")
  assert.deepEqual(JSON.parse(fs.readFileSync(stateCache, "utf8")).map(station => station.uuid).sort(),
    stations.map(station => station.uuid).sort())

  // A fresh cache must serve the state without touching the network.
  const cached = spawnSync(path.join(project, "radio-fetch"), ["state", "CALIFORNIA"], {
    encoding: "utf8",
    env: { ...env, RADIO_ATLAS_TEST_CURL_FAIL: "1" },
  })
  assert.equal(cached.status, 0, cached.stderr)
  assert.deepEqual(JSON.parse(cached.stdout).map(station => station.uuid).sort(),
    stations.map(station => station.uuid).sort())

  // A cache containing another state must be rejected instead of served.
  fs.writeFileSync(stateCache, JSON.stringify([
    { uuid: "cccccccc-1111-1111-1111-cccccccccccc", countryCode: "US", state: "Texas" },
  ]))
  const rejected = spawnSync(path.join(project, "radio-fetch"), ["state", "CALIFORNIA"], {
    encoding: "utf8",
    env: { ...env, RADIO_ATLAS_TEST_CURL_FAIL: "1" },
  })
  assert.notEqual(rejected.status, 0, "A mismatched state cache must not be served")

  for (const invalid of ["", "../etc/passwd", "Cali/fornia", "C".repeat(101)]) {
    const invalidResult = fetch("state", invalid)
    assert.equal(invalidResult.status, 2, `Reject state name: ${invalid}`)
    assert.match(invalidResult.stderr, /State name is invalid/)
  }

  const empty = fetch("state", "WYOMING")
  assert.equal(empty.status, 0, empty.stderr)
  assert.deepEqual(JSON.parse(empty.stdout), [], "A state without stations returns an empty list")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}

console.log("State fetch tests passed")
