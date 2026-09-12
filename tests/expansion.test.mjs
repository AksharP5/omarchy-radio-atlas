import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const schedule = source.match(/function scheduleWorldExpansion\(delay\) \{([\s\S]*?)\n  \}/)[1]
const complete = source.match(/id: worldExpandProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const open = source.match(/function openWindow\(payloadJson\) \{([\s\S]*?)\n  \}/)[1]
const model = vm.createContext({})
vm.runInContext(fs.readFileSync(new URL("../RadioModel.js", import.meta.url), "utf8"), model)

function session() {
  const delays = []
  const context = vm.createContext({
    opened: true,
    worldStationLimit: 5000,
    worldExpansionMisses: 0,
    worldStations: [{ uuid: "first" }],
    mode: "world",
    RadioModel: model,
    panel: {},
    windowRevealTimer: { stop() {} },
    loadState() {},
    Qt: { callLater() {} },
    worldExpandTimer: { interval: 0, restart() { delays.push(this.interval) } },
  })
  context.root = context
  vm.runInContext(`function scheduleWorldExpansion(delay) {${schedule}}
    function complete(exitCode) {${complete}}
    function openWindow(payloadJson) {${open}}`, context)
  return {
    context,
    delays,
    finish(rows, exitCode = 0) {
      context.worldExpandOutput = JSON.stringify(rows)
      context.complete(exitCode)
    },
  }
}

for (const [rows, exitCode] of [[[ { uuid: "first" } ], 0], [[], 0], [null, 0], [[], 1]]) {
  const run = session()
  const original = run.context.worldStations
  for (let i = 0; i < 3; i++) run.finish(rows, exitCode)
  assert.equal(run.context.worldExpansionMisses, 3)
  assert.equal(run.delays.length, 2)
  assert.equal(run.context.worldStations, original)
  run.context.openWindow("{}")
  assert.equal(run.context.worldExpansionMisses, 0)
  assert.equal(run.delays.at(-1), 800)
}

const run = session()
run.finish([{ uuid: "first" }])
run.finish([{ uuid: "first" }])
run.finish([{ uuid: "second" }])
assert.equal(run.context.worldExpansionMisses, 0)
assert.equal(run.context.worldStations.length, 2)
assert.equal(run.delays.at(-1), 1600)
run.context.opened = false
run.finish([{ uuid: "third" }])
assert.equal(run.context.worldStations.length, 2)
assert.equal(run.delays.length, 3)
console.log("World expansion tests passed")
