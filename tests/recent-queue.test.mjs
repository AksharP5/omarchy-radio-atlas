import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const functions = source.match(/  function (?:recordPlayed|startRecordPlayed|writeSelection)\([\s\S]*?\n  \}/g).join("\n")
const complete = source.match(/id: historyProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)
const stations = ["first", "queued", "latest", "failed", "superseded"]
  .map(uuid => ({ uuid, name: uuid, url: `https://example.com/${uuid}` }))

function session() {
  const callbacks = []
  const recent = []
  const savedStations = new Map()
  let selection = []
  let activeStation = null
  let activeUuid = ""
  let restartUuid = ""
  const context = vm.createContext({
    RadioModel: model,
    runtimeStations: stations,
    pendingRecentRequest: null,
    localReloadPending: false,
    statePath: "/radio-state",
    historySelectionPath: "/history-selection.json",
    requestLocalStateReload() {},
    historyPlaylistFile: {
      readSucceeded: false,
      reload() { this.readSucceeded = true },
      text() { return JSON.stringify(context.runtimeStations) },
    },
    historySelectionFile: {
      saveSucceeded: false,
      setText(text) { selection = JSON.parse(text); this.saveSucceeded = true },
    },
    Qt: { callLater(callback) { callbacks.push(callback) } },
    historyProcess: {
      command: [],
      get running() { return Boolean(activeUuid) },
      set running(value) {
        if (!value) { activeUuid = ""; return }
        // Quickshell retains a requested restart while the process is running.
        if (activeUuid) restartUuid = this.command[2]
        else {
          activeUuid = this.command[2]
          const rows = this.command[3] === "selection" ? selection : context.runtimeStations
          activeStation = rows.find(row => row.uuid === activeUuid)
        }
      },
    },
  })
  context.root = context
  vm.runInContext(`${functions}\nfunction complete(exitCode) {${complete}}`, context)
  function finish(exitCode = 0) {
    if (exitCode === 0) {
      const previous = recent.indexOf(activeUuid)
      if (previous >= 0) recent.splice(previous, 1)
      recent.unshift(activeUuid)
      savedStations.set(activeUuid, activeStation)
    }
    activeUuid = ""
    context.complete(exitCode)
    if (restartUuid) { activeUuid = restartUuid; restartUuid = "" }
  }
  function flush() {
    while (callbacks.length) callbacks.shift()()
  }
  return {
    context, recent, savedStations, finish, flush,
    drain() {
      flush()
      for (let remaining = 10; activeUuid; remaining--) {
        assert.ok(remaining > 0, "History updates must finish")
        finish()
        flush()
      }
    },
  }
}

for (const updateBeforeDeferredStart of [true, false]) {
  const run = session()
  run.context.recordPlayed("first")
  run.context.recordPlayed("queued")
  run.finish()
  if (!updateBeforeDeferredStart) run.flush()
  run.context.recordPlayed("latest")
  run.drain()
  assert.equal(run.recent[0], "latest",
    "A deferred history update must not replace the latest played station")
  assert.deepEqual(run.recent, updateBeforeDeferredStart
    ? ["latest", "first"] : ["latest", "queued", "first"])
}

const failed = session()
failed.context.recordPlayed("failed")
failed.context.recordPlayed("superseded")
failed.context.recordPlayed("latest")
failed.finish(3)
failed.drain()
assert.deepEqual(failed.recent, ["latest"],
  "A failed write must still release the latest pending history update")

const changed = session()
changed.context.runtimeStations = [stations[0]]
changed.context.recordPlayed("first")
changed.context.runtimeStations = [stations[1]]
changed.context.recordPlayed("queued")
changed.context.runtimeStations = [stations[2]]
changed.finish()
changed.drain()
assert.deepEqual(changed.recent, ["queued", "first"])
assert.deepEqual(changed.savedStations.get("queued"), stations[1],
  "Queued history must retain full station details after playback changes")

const failedSnapshot = session()
failedSnapshot.context.recordPlayed("first")
failedSnapshot.finish()
const updated = { ...stations[0], name: "Updated station", url: "https://example.com/updated" }
failedSnapshot.context.runtimeStations = [updated]
failedSnapshot.context.historySelectionFile.setText = () => {}
failedSnapshot.context.recordPlayed("first")
failedSnapshot.drain()
assert.deepEqual(failedSnapshot.savedStations.get("first"), updated,
  "A failed snapshot write must fall back without reading an older snapshot")

console.log("Recent queue tests passed")
