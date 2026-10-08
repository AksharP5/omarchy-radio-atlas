import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const functions = source.match(/  function (?:applyPlayerState|playerGeneration|playSelected|playlistScope|playStation|playPendingStation|cancelPendingFetch|cancelPendingPlay|stopPlayer|tuneRandom|startFetch|showWorld|showFavorites|previewSearch|search|browseCountry|setStationList)\([\s\S]*?\n  \}/g).join("\n")
const complete = source.match(/id: fetchProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const stopComplete = source.match(/id: stopProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const playerComplete = source.match(/id: playerActionProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const edit = source.match(/id: searchField[\s\S]*?onTextEdited: \{([\s\S]*?)\n          \}/)[1]
const debounce = source.match(/id: searchDebounce[\s\S]*?onTriggered: ([^\n]+)/)[1]
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)

function session() {
  const requests = []
  const callbacks = []
  const played = []
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
    randomPlaybackPending: false,
    randomPlayGeneration: "0",
    playerRunning: false,
    playerStopped: false,
    playingStationUuid: "",
    recordedStationUuid: "",
    pendingVolume: -1,
    playerError: "",
    playPreparing: false,
    playCancellationRequested: false,
    activePlayGeneration: "0",
    pendingPlayStation: null,
    pendingPlayScope: "",
    pendingPlayStations: [],
    pendingPlayGeneration: "",
    playerGenerationFile: {
      value: "0", reload() {}, waitForJob() {}, text() { return this.value },
    },
    localStopStatusPending: false,
    playerActionProcess: {
      action: "", command: [],
      get running() { return this.active || false },
      set running(value) {
        this.active = value
        if (value && this.action === "play") played.push(this.command[2])
      },
    },
    stopProcess: { running: false, command: [], output: "" },
    playerPath: "/radio-player",
    playSelectionPath: "/play-selection.json",
    playSelectionFile: {},
    writeSelection() { return true },
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
    setSelection(index) { context.selectedStation = context.results[index] || null },
    highlightStationCountry() {},
    recordPlayed() {},
    keyCatcher: { forceActiveFocus() {} },
    restorePlayingCountry() {},
    scheduleWorldExpansion() {},
    randomExclusions() { return "latest-random-exclusions" },
    Qt: { callLater(callback) { callbacks.push(callback) } },
  })
  context.root = context
  Object.defineProperty(context, "displayStations", { get: () => context.results })
  Object.defineProperty(context, "playerActionBusy", {
    get: () => context.playerActionProcess.running || context.stopProcess.running,
  })
  vm.runInContext(`${functions}
    function complete(exitCode) {${complete}}
    function stopComplete(exitCode) {${stopComplete}}
    function playerComplete(exitCode) {${playerComplete}}
    function editText(text) {${edit}}
    function debounce() {${debounce}}`, context)
  return {
    context,
    requests,
    played,
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
    finishStop(state, exitCode = 0, acknowledgment) {
      context.stopProcess.running = false
      if (exitCode === 0 && !acknowledgment) {
        const canceledGeneration = context.playerGenerationFile.value
        const stopGeneration = String(Number(canceledGeneration) + 1)
        context.playerGenerationFile.value = stopGeneration
        acknowledgment = { canceledGeneration, stopGeneration }
      }
      context.stopProcess.output = JSON.stringify({ ...state, ...acknowledgment })
      context.stopComplete(exitCode)
    },
    finishPlayer(exitCode) {
      context.playerActionProcess.running = false
      context.playPreparing = false
      context.playerComplete(exitCode)
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

const failedSearch = session()
failedSearch.edit("jazz")
failedSearch.debounce()
failedSearch.finish([], 1)
assert.equal(failedSearch.context.results[0].uuid, "cached-jazz", "A failed search keeps the local preview")
assert.equal(failedSearch.context.fetchError, "Showing cached stations · Radio Browser is unavailable")
assert.equal(failedSearch.context.fetching, false)

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

for (const phase of ["active", "queued", "deferred"]) {
  const run = session()
  if (phase !== "active") run.context.startFetch("world", "")
  run.context.tuneRandom()
  if (phase === "deferred") run.finish([])
  run.context.stopPlayer()
  assert.equal(run.context.stopProcess.running, true, "Stop must still stop the existing player")
  if (phase === "queued") run.finish([])
  run.flush()
  if (phase === "active") run.finish([{ uuid: "canceled-random" }])
  assert.deepEqual(run.played, [], `${phase} random request must not play after Stop`)
  if (phase !== "active")
    assert.deepEqual(run.requests, [["world"]], "Canceled random work must not start")

  run.context.stopProcess.running = false
  run.context.tuneRandom()
  run.finish([{ uuid: "requested-again" }])
  assert.deepEqual(run.played, ["requested-again"], "A later Random request must still play")
  assert.equal(run.context.randomPlaybackPending, false)
}

for (const [rows, exitCode] of [[[], 0], [[], 1], [null, 0]]) {
  const run = session()
  run.context.tuneRandom()
  run.finish(rows, exitCode)
  assert.equal(run.context.randomPlaybackPending, false, "Failed or empty tuning is no longer pending")
  assert.deepEqual(run.played, [])
}

const playing = { running: true }
const stopped = { running: false }
for (const statusBeforeCompletion of [false, true]) {
  const run = session()
  run.context.applyPlayerState(JSON.stringify(playing))
  run.context.stopPlayer()
  run.context.tuneRandom()
  if (statusBeforeCompletion) run.context.applyPlayerState(JSON.stringify(stopped))
  run.finishStop(stopped)
  if (!statusBeforeCompletion) run.context.applyPlayerState(JSON.stringify(stopped))
  run.finish([{ uuid: "requested-after-stop" }])
  assert.deepEqual(run.played, ["requested-after-stop"],
    "A local Stop's delayed status must preserve a newer Random request")
}

for (const initiallyRunning of [false, true]) {
  const run = session()
  run.context.applyPlayerState(JSON.stringify({ running: initiallyRunning }))
  run.context.stopPlayer()
  run.context.tuneRandom()
  // FileView may coalesce the stop write with later playback status.
  run.finishStop(stopped)
  run.finish([{ uuid: "requested-after-stop" }])
  assert.deepEqual(run.played, ["requested-after-stop"])
  run.context.applyPlayerState(JSON.stringify(playing))
  run.context.tuneRandom()
  run.context.playerGenerationFile.value = "2"
  run.context.applyPlayerState(JSON.stringify(stopped))
  run.finish([{ uuid: "canceled-by-external-stop" }])
  assert.deepEqual(run.played, ["requested-after-stop"],
    "A completed local Stop must not hide a later external Stop")
}

const failedStop = session()
failedStop.context.applyPlayerState(JSON.stringify(playing))
failedStop.context.stopPlayer()
failedStop.context.tuneRandom()
failedStop.finishStop({}, 1)
assert.equal(failedStop.context.playerError, "Could not stop the player")
failedStop.context.playerGenerationFile.value = "1"
failedStop.context.applyPlayerState(JSON.stringify(stopped))
failedStop.finish([{ uuid: "canceled-after-failed-stop" }])
assert.deepEqual(failedStop.played, [], "A failed local Stop must not hide an external Stop")

const queuedPlay = session()
queuedPlay.context.applyPlayerState(JSON.stringify(playing))
queuedPlay.context.playerActionProcess.running = true
queuedPlay.context.playPreparing = true
queuedPlay.context.pendingPlayStation = { uuid: "queued-before-stop" }
queuedPlay.context.pendingPlayScope = "results"
queuedPlay.context.pendingPlayStations = [queuedPlay.context.pendingPlayStation]
queuedPlay.context.pendingPlayGeneration = "0"
queuedPlay.context.playerGenerationFile.value = "1"
queuedPlay.context.applyPlayerState(JSON.stringify({ running: true, stopped: true }))
queuedPlay.context.playerActionProcess.running = false
queuedPlay.context.playPendingStation()
assert.deepEqual(queuedPlay.played, [], "External Stop must discard a queued playback request")
assert.equal(queuedPlay.context.playCancellationRequested, true,
  "Preparation canceled by external Stop must not report a playback failure")

for (const localStop of [true, false]) {
  const afterStop = session()
  afterStop.context.applyPlayerState(JSON.stringify(playing))
  afterStop.context.playerActionProcess.running = true
  afterStop.context.playPreparing = true
  if (localStop) afterStop.context.stopPlayer()
  else afterStop.context.applyPlayerState(JSON.stringify({ running: true, stopped: true }))
  afterStop.context.playStation({ uuid: "requested-after-stop" }, "results", [])
  if (localStop) afterStop.finishStop(stopped)
  afterStop.context.playerActionProcess.running = false
  afterStop.context.playPendingStation()
  afterStop.flush()
  assert.deepEqual(afterStop.played, ["requested-after-stop"],
    "A new selection after Stop must still play when preparation finishes")
}

for (const requestAfterStop of [false, true]) {
  const repeatedStop = session()
  repeatedStop.context.applyPlayerState(JSON.stringify({ running: true, stopped: true }))
  repeatedStop.context.playerActionProcess.running = true
  repeatedStop.context.playerActionProcess.action = "play"
  repeatedStop.context.playPreparing = true
  repeatedStop.context.activePlayGeneration = "1"
  repeatedStop.context.pendingPlayStation = { uuid: "queued-selection" }
  repeatedStop.context.pendingPlayGeneration = requestAfterStop ? "2" : "1"
  repeatedStop.context.playerGenerationFile.value = "2"
  repeatedStop.context.applyPlayerState(JSON.stringify({ running: true, stopped: true }))
  repeatedStop.finishPlayer(4)
  repeatedStop.flush()
  assert.deepEqual(repeatedStop.played, requestAfterStop ? ["queued-selection"] : [],
    "A repeated Stop discards older queued playback and allows a later selection")
  assert.equal(repeatedStop.context.playerError, "", "Intentional cancellation is not a playback failure")
}

for (const phase of ["active", "queued", "deferred"]) {
  const repeatedStop = session()
  repeatedStop.context.applyPlayerState(JSON.stringify({ running: true, stopped: true }))
  repeatedStop.context.playerGenerationFile.value = "1"
  if (phase !== "active") repeatedStop.context.startFetch("world", "")
  repeatedStop.context.tuneRandom()
  if (phase === "deferred") repeatedStop.finish([])
  repeatedStop.context.playerGenerationFile.value = "2"
  repeatedStop.context.applyPlayerState(JSON.stringify({ running: true, stopped: true }))
  if (phase === "queued") repeatedStop.finish([])
  repeatedStop.flush()
  if (phase === "active") repeatedStop.finish([{ uuid: "canceled-random" }])
  assert.deepEqual(repeatedStop.played, [], `${phase} random tuning must respect repeated Stop`)
  assert.equal(repeatedStop.context.randomPlaybackPending, false)
  if (phase !== "active") assert.deepEqual(repeatedStop.requests, [["world"]])
}

const delayedExternalStatus = session()
delayedExternalStatus.context.applyPlayerState(JSON.stringify(playing))
delayedExternalStatus.context.playerGenerationFile.value = "1"
delayedExternalStatus.context.tuneRandom()
delayedExternalStatus.context.applyPlayerState(JSON.stringify({ running: true, stopped: true }))
delayedExternalStatus.finish([{ uuid: "requested-after-external-stop" }])
assert.deepEqual(delayedExternalStatus.played, ["requested-after-external-stop"],
  "A delayed external Stop notification must preserve newer Random intent")

for (const phase of ["active", "queued", "deferred"]) {
  const duringStop = session()
  if (phase !== "active") duringStop.context.startFetch("world", "")
  duringStop.context.stopPlayer()
  duringStop.context.tuneRandom()
  if (phase === "deferred") duringStop.finish([])
  duringStop.context.playerGenerationFile.value = "1"
  if (phase === "queued") duringStop.finish([])
  duringStop.flush()
  duringStop.finish([{ uuid: "requested-during-stop" }])
  assert.deepEqual(duringStop.played, [], "Playback waits for the panel Stop to finish")
  duringStop.finishStop(stopped, 0, { canceledGeneration: "0", stopGeneration: "1" })
  duringStop.flush()
  assert.deepEqual(duringStop.played, ["requested-during-stop"],
    `${phase} Random requested during local Stop must survive an early fetch completion`)
}

for (const phase of ["active", "queued", "deferred", "result"]) {
  for (const requestAfterExternalStop of [false, true]) {
    const overlap = session()
    if (phase === "queued" || phase === "deferred") overlap.context.startFetch("world", "")
    overlap.context.stopPlayer()
    if (requestAfterExternalStop) overlap.context.playerGenerationFile.value = "1"
    overlap.context.tuneRandom()
    if (!requestAfterExternalStop) overlap.context.playerGenerationFile.value = "1"
    if (phase === "deferred") overlap.finish([])
    overlap.context.playerGenerationFile.value = "2"
    if (phase === "queued") overlap.finish([])
    overlap.flush()
    if (phase === "result") overlap.finish([{ uuid: "overlap-random" }])
    overlap.finishStop(stopped, 0, { canceledGeneration: "1", stopGeneration: "2" })
    overlap.flush()
    if (phase !== "result") overlap.finish([{ uuid: "overlap-random" }])
    assert.deepEqual(overlap.played, requestAfterExternalStop ? ["overlap-random"] : [],
      `${phase} Random must respect the later media Stop during a panel Stop`)
    assert.equal(overlap.context.playerError, "")
  }
}

for (const externalStopAfterCommit of [false, true]) {
  const overlap = session()
  overlap.context.stopPlayer()
  overlap.context.pendingPlayStation = { uuid: "queued-during-stop" }
  overlap.context.pendingPlayScope = "results"
  overlap.context.pendingPlayStations = [overlap.context.pendingPlayStation]
  overlap.context.pendingPlayGeneration = "0"
  overlap.context.playerGenerationFile.value = "2"
  overlap.finishStop(stopped, 0, externalStopAfterCommit
    ? { canceledGeneration: "0", stopGeneration: "1" }
    : { canceledGeneration: "1", stopGeneration: "2" })
  overlap.flush()
  assert.deepEqual(overlap.played, [], "A panel Stop acknowledgment cannot revive a canceled selection")
}

console.log("Search, country, and random queue tests passed")
