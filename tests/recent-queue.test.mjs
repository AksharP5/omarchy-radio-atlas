import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const functions = source.match(/  function (?:recordPlayed|startRecordPlayed)\([\s\S]*?\n  \}/g).join("\n")
const complete = source.match(/id: historyProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]

function session() {
  const callbacks = []
  const recent = []
  let activeUuid = ""
  let restartUuid = ""
  const context = vm.createContext({
    pendingRecentUuid: "",
    localReloadPending: false,
    statePath: "/radio-state",
    requestLocalStateReload() {},
    Qt: { callLater(callback) { callbacks.push(callback) } },
    historyProcess: {
      command: [],
      get running() { return Boolean(activeUuid) },
      set running(value) {
        if (!value) { activeUuid = ""; return }
        // Quickshell retains a requested restart while the process is running.
        if (activeUuid) restartUuid = this.command[2]
        else activeUuid = this.command[2]
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
    }
    activeUuid = ""
    context.complete(exitCode)
    if (restartUuid) { activeUuid = restartUuid; restartUuid = "" }
  }
  function flush() {
    while (callbacks.length) callbacks.shift()()
  }
  return {
    context, recent, finish, flush,
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

console.log("Recent queue tests passed")
