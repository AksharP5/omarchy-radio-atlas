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

const stations = [
  { uuid: "a", latitude: 0, longitude: 0 },
  { uuid: "b", latitude: 0, longitude: 180 }
]
assert.equal(model.stationAt(stations, 100, 100, 200, 200, 1, 0, 0, 12).uuid, "a")
assert.equal(model.compactTags("jazz, soul, jazz", 2), "jazz · soul")

console.log("RadioModel tests passed")
