import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const functions = source.match(/  function (?:cancelPendingFetch|startFetch|showWorld|showFavorites|previewSearch|search|browseCountry|setStationList)\([\s\S]*?\n  \}/g).join("\n")
const complete = source.match(/id: fetchProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const edit = source.match(/id: searchField[\s\S]*?onTextEdited: \{([\s\S]*?)\n          \}/)[1]
const debounce = source.match(/id: searchDebounce[\s\S]*?onTriggered: ([^\n]+)/)[1]
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)

function session() {
  const requests = []
  const callbacks = []
  const context = vm.createContext({
    RadioModel: model,
    mode: "world",
    worldStationLimit: 5000,
    worldStations: [{ uuid: "cached-jazz", name: "Jazz" }],
    countryNames: {},
    countries: [],
    browsedCountryCode: "",
    countryCacheLoaded: false,
    activeCountryCode: "",
    activeCountryName: "",
    favorites: [],
    results: [],
    selectedStation: null,
    keyboardSelectionVisible: false,
    fetchPath: "/radio-fetch",
    fetchAction: "",
    fetchValue: "",
    pendingFetchAction: "",
    pendingFetchValue: "",
    fetchError: "",
    fetchOutput: "",
    fetchStderr: "",
    fetching: false,
    searchField: { text: "" },
    searchDebounce: {
      running: false,
      restart() { this.running = true },
      stop() { this.running = false },
    },
    fetchProcess: {
      command: [],
      get running() { return this.active || false },
      set running(value) {
        this.active = value
        if (value) requests.push(Array.from(this.command).slice(1))
      },
    },
    setSelection() {},
    keyCatcher: { forceActiveFocus() {} },
    restorePlayingCountry() {},
    scheduleWorldExpansion() {},
    randomExclusions() { return "latest-random-exclusions" },
    Qt: { callLater(callback) { callbacks.push(callback) } },
  })
  context.root = context
  Object.defineProperty(context, "displayStations", { get: () => context.results })
  vm.runInContext(`${functions}
    function complete(exitCode) {${complete}}
    function editText(text) {${edit}}
    function debounce() {${debounce}}`, context)
  return {
    context,
    requests,
    edit(query) {
      context.searchField.text = query
      context.editText(query)
    },
    debounce() {
      assert.equal(context.searchDebounce.running, true)
      context.searchDebounce.running = false
      context.debounce()
    },
    finish(rows = [], exitCode = 0) {
      context.fetchProcess.running = false
      context.fetchOutput = JSON.stringify(rows)
      context.complete(exitCode)
    },
    flush() {
      while (callbacks.length) callbacks.shift()()
    },
  }
}

for (const editAfterCompletion of [false, true]) {
  const run = session()
  run.edit("j")
  run.debounce()
  run.edit("ja")
  run.debounce()
  if (!editAfterCompletion) run.edit("jazz")
  run.finish([{ uuid: "obsolete-j", name: "Old results" }])
  if (editAfterCompletion) run.edit("jazz")
  run.flush()
  assert.deepEqual(run.requests, [["search", "j"]], "Obsolete queued query must not start")
  assert.equal(run.context.results[0].uuid, "cached-jazz", "Keep the latest local preview")
  run.debounce()
  assert.deepEqual(run.requests, [["search", "j"], ["search", "jazz"]])
  run.finish([{ uuid: "remote-jazz" }])
  assert.equal(run.context.results[0].uuid, "remote-jazz")
  assert.equal(run.context.fetching, false)
}

const latest = session()
latest.edit("j")
latest.debounce()
latest.edit("  jazz  ")
latest.debounce()
latest.finish([{ uuid: "obsolete-j" }])
latest.flush()
assert.deepEqual(latest.requests, [["search", "j"], ["search", "jazz"]])
latest.finish([{ uuid: "remote-jazz" }])
assert.equal(latest.context.results[0].uuid, "remote-jazz")

const changedMode = session()
changedMode.edit("j")
changedMode.debounce()
changedMode.edit("ja")
changedMode.debounce()
changedMode.finish()
changedMode.context.showFavorites()
changedMode.flush()
assert.deepEqual(changedMode.requests, [["search", "j"]])
assert.equal(changedMode.context.mode, "favorites")

// World data still fills the cache while the latest country or random request waits.
for (const [action, value] of [["country", "DE"], ["random", "old-exclusions"]]) {
  const run = session()
  run.context.startFetch("world", "")
  run.context.mode = action
  if (action === "country") run.context.browsedCountryCode = value
  run.context.startFetch(action, value)
  run.finish([{ uuid: "fresh-world" }])
  run.flush()
  assert.deepEqual(run.requests, [
    ["world"],
    [action, action === "random" ? "latest-random-exclusions" : value],
  ])
  assert.equal(run.context.worldStations.some(station => station.uuid === "fresh-world"), true)
}

const changedCountry = session()
changedCountry.context.startFetch("world", "")
changedCountry.context.browseCountry("DE", "Germany")
changedCountry.finish()
changedCountry.context.browseCountry("GB", "United Kingdom")
changedCountry.flush()
assert.deepEqual(changedCountry.requests, [["world"], ["country", "GB"]],
  "A country superseded before the deferred callback must not start")
changedCountry.finish([], 1)
changedCountry.flush()
assert.deepEqual(changedCountry.requests, [["world"], ["country", "GB"]])
assert.equal(changedCountry.context.fetchError, "Radio Browser is unavailable. Try again shortly.",
  "The current country's network failure must remain visible")
assert.equal(changedCountry.context.fetching, false)

const leftCountry = session()
leftCountry.context.startFetch("world", "")
leftCountry.context.browseCountry("DE", "Germany")
leftCountry.finish()
leftCountry.context.showFavorites()
leftCountry.flush()
assert.deepEqual(leftCountry.requests, [["world"]],
  "Leaving country browsing must discard its deferred request")

for (const exitCode of [0, 1]) {
  const staleCountry = session()
  staleCountry.context.browseCountry("DE", "Germany")
  staleCountry.context.browsedCountryCode = "GB"
  staleCountry.context.results = [{ uuid: "gb-station", countryCode: "GB" }]
  staleCountry.context.fetchError = "Current country failed"
  staleCountry.finish([{ uuid: "de-station", countryCode: "DE" }], exitCode)
  assert.equal(staleCountry.context.fetchError, "Current country failed",
    "An obsolete country's completion must not change the current error")
  assert.equal(staleCountry.context.results[0].uuid, "gb-station")
}

console.log("Search and country queue tests passed")
