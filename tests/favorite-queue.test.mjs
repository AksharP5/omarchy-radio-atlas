import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const functions = source.match(/  function (?:toggleFavorite|startFavorite|startNextFavorite|writeSelection|applyLocalState)\([\s\S]*?\n  \}/g).join("\n")
const complete = source.match(/id: stateProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const completeHistory = source.match(/id: historyProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)
const rows = ["first", "queued", "new-search"].map(uuid => ({ uuid, name: uuid }))

function session() {
  const callbacks = []
  const saved = new Map()
  let selection = []
  let activeUuid = ""
  let restartUuid = ""
  let reloads = 0
  const context = vm.createContext({
    RadioModel: model,
    remoteMode: true,
    displayStations: rows.slice(0, 2),
    pendingFavoriteRequests: [],
    pendingRecentRequest: null,
    localError: "",
    localReloadPending: false,
    statePath: "/radio-state",
    favoriteSelectionPath: "/favorite-selection.json",
    favoriteSelectionFile: {
      saveSucceeded: false,
      setText(text) { selection = JSON.parse(text); this.saveSucceeded = true },
    },
    applyLocalState() {},
    refreshLocalSelection() {},
    requestLocalStateReload() { reloads++ },
    Qt: { callLater(callback) { callbacks.push(callback) } },
    stateProcess: {
      command: [],
      get running() { return Boolean(activeUuid) },
      set running(value) {
        if (!value) { activeUuid = ""; return }
        // Quickshell retains a requested restart when the process is still running.
        if (activeUuid) restartUuid = this.command[2]
        else activeUuid = this.command[2]
      },
    },
  })
  context.root = context
  vm.runInContext(`${functions}\nfunction complete(exitCode) {${complete}}\nfunction completeHistory(exitCode) {${completeHistory}}`, context)
  function finish() {
    const station = selection.find(row => row.uuid === activeUuid)
    if (station) {
      if (saved.has(activeUuid)) saved.delete(activeUuid)
      else saved.set(activeUuid, station)
    }
    activeUuid = ""
    context.complete(station ? 0 : 3)
    if (restartUuid) { activeUuid = restartUuid; restartUuid = "" }
  }
  function flush() {
    while (callbacks.length) callbacks.shift()()
  }
  return {
    context, saved, finish, flush,
    get reloads() { return reloads },
    drain() {
      flush()
      for (let remaining = 10; activeUuid; remaining--) {
        assert.ok(remaining > 0, "Favorite requests must finish")
        finish()
        flush()
      }
    },
  }
}

for (const clickBeforeDeferredStart of [true, false]) {
  const run = session()
  run.context.toggleFavorite(rows[0].uuid)
  run.context.toggleFavorite(rows[1].uuid)
  run.finish()
  if (!clickBeforeDeferredStart) run.flush()
  run.context.displayStations = [rows[2]]
  run.context.toggleFavorite(rows[2].uuid)
  run.drain()
  assert.deepEqual([...run.saved.values()], rows,
    "Every Favorite must retain its station data when another search is shown")
}

const repeated = session()
repeated.context.toggleFavorite(rows[0].uuid)
repeated.context.toggleFavorite(rows[0].uuid)
repeated.finish()
repeated.context.displayStations = [rows[2]]
repeated.context.toggleFavorite(rows[2].uuid)
repeated.drain()
assert.deepEqual([...repeated.saved.values()], [rows[2]],
  "Repeated toggles must cancel each other without losing another Favorite")

const failed = session()
failed.context.toggleFavorite(rows[0].uuid)
failed.context.toggleFavorite(rows[1].uuid)
failed.context.displayStations = [rows[2]]
failed.context.toggleFavorite(rows[2].uuid)
const write = failed.context.favoriteSelectionFile.setText
failed.context.favoriteSelectionFile.setText = function(text) {
  if (JSON.parse(text)[0].uuid !== rows[1].uuid) write.call(this, text)
}
failed.finish()
failed.drain()
assert.deepEqual([...failed.saved.values()], [rows[0], rows[2]],
  "A failed selection write must skip that Favorite and release the next queued request")

const lastFailed = session()
lastFailed.context.toggleFavorite(rows[0].uuid)
lastFailed.context.toggleFavorite(rows[1].uuid)
lastFailed.context.favoriteSelectionFile.setText = () => {}
lastFailed.finish()
lastFailed.drain()
assert.equal(lastFailed.reloads, 1,
  "A final failed snapshot must still refresh an earlier successful Favorite")
lastFailed.context.stateProcess.action = "get"
lastFailed.context.localReloadPending = false
lastFailed.context.output = JSON.stringify({ favorites: [...lastFailed.saved.values()], recent: [] })
lastFailed.context.complete(0)
assert.deepEqual(Array.from(lastFailed.context.favorites, row => row.uuid), [rows[0].uuid])
assert.equal(lastFailed.context.localError, "Favorite could not be updated",
  "Refreshing successful Favorites must preserve the failed selection's error")

const backgroundHistory = session()
backgroundHistory.context.favoriteSelectionFile.setText = () => {}
backgroundHistory.context.toggleFavorite(rows[0].uuid)
backgroundHistory.context.completeHistory(0)
assert.equal(backgroundHistory.context.localError, "Favorite could not be updated",
  "Successful background history must not hide an unsaved Favorite")
backgroundHistory.context.stateProcess.action = "get"
backgroundHistory.context.output = JSON.stringify({ favorites: [], recent: [rows[0]] })
backgroundHistory.context.complete(0)
assert.equal(backgroundHistory.context.localError, "Favorite could not be updated")

const failedHistory = session()
failedHistory.context.completeHistory(4)
failedHistory.context.stateProcess.action = "favorite"
failedHistory.context.complete(0)
assert.equal(failedHistory.context.localError, "Listening history could not be updated",
  "A successful Favorite must not hide failed listening history")
failedHistory.context.stateProcess.action = "get"
failedHistory.context.output = JSON.stringify({ favorites: [rows[0]], recent: [] })
failedHistory.context.complete(0)
assert.equal(failedHistory.context.localError, "Listening history could not be updated",
  "Loading saved stations cannot establish that a failed history write succeeded")
failedHistory.context.completeHistory(0)
assert.equal(failedHistory.context.localError, "")

console.log("Favorite queue tests passed")
