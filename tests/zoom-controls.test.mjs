import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const controls = source.match(/          Rectangle \{\n            id: zoomControls\n[\s\S]*?\n          \}/)?.[0]
assert.ok(controls, "Could not find the production zoom controls")
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
assert.ok(fs.existsSync(path.join(shellDirectory, "Ui/Button.qml")),
  "Set OMARCHY_SHELL_DIR to an Omarchy checkout’s shell directory")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-zoom-controls-"))

try {
  // Test the production controls with the real Omarchy button and theme.
  fs.symlinkSync(path.resolve(shellDirectory), path.join(directory, "qs"))
  fs.cpSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"), { recursive: true })
  for (const name of ["Globe.qml", "RadioModel.js"])
    fs.copyFileSync(new URL("../" + name, import.meta.url), path.join(directory, name))
  fs.writeFileSync(path.join(directory, "tst_zoom_controls.qml"), `
import QtQuick
import QtTest
import qs.Ui
import qs.Commons

TestCase {
  id: root
  name: "ZoomControls"
  width: 800
  height: 600
  visible: true
  when: windowShown
  property color foreground: "white"
  property color background: "#111111"
  property color accent: "cyan"
  property color dim: "gray"
  property color faint: "#333333"

  Item { id: keyCatcher; focus: true }
  Globe {
    id: globe
    anchors.fill: parent
    onInteractionStarted: keyCatcher.forceActiveFocus()
  }
  Text {
    id: signalCount
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    text: "0 signals"
  }

  ${controls}

  function init() {
    globe.stopZoomAnimation()
    globe.stopKineticRotation(true)
    globe.globeScale = 1
    keyCatcher.forceActiveFocus()
    waitForRendering(globe)
  }

  function cleanup() {
    globe.stopZoomAnimation()
    globe.stopKineticRotation(true)
  }

  function test_keyboardActivation() {
    keyClick(Qt.Key_Tab)
    verify(zoomInButton.activeFocus, "Tab must reach Zoom in")
    keyClick(Qt.Key_Return)
    tryCompare(globe, "globeScale", 1.5)
    verify(keyCatcher.activeFocus, "Return focus to the normal keyboard controls")
    keyClick(Qt.Key_Tab)
    keyClick(Qt.Key_Tab)
    verify(zoomOutButton.activeFocus, "Tab must reach Zoom out")
    keyClick(Qt.Key_Space)
    tryCompare(globe, "globeScale", 1)
  }

  function test_pointerActivationAndLimits() {
    mouseClick(zoomInButton)
    tryCompare(globe, "globeScale", 1.5)
    mouseClick(zoomOutButton)
    tryCompare(globe, "globeScale", 1)
    globe.globeScale = globe.maximumScale
    verify(!zoomInButton.enabled)
    mouseClick(zoomInButton)
    compare(globe.globeScale, globe.maximumScale)
    globe.globeScale = globe.minimumScale
    verify(!zoomOutButton.enabled)
    mouseClick(zoomOutButton)
    compare(globe.globeScale, globe.minimumScale)
  }

  function test_rapidCommands_data() {
    return [
      { tag: "reverse-before-first-frame", reverse: true, expected: 1 },
      { tag: "accumulate-before-first-frame", reverse: false, expected: 2.25 }
    ]
  }

  function test_rapidCommands(data) {
    // Deliver both button actions in one event turn before animation advances.
    zoomInButton.clicked()
    if (data.reverse) zoomOutButton.clicked()
    else zoomInButton.clicked()
    wait(250)
    compare(globe.globeScale, data.expected)
  }

  function test_wheelInterruptsButtonAnimation() {
    zoomInButton.clicked()
    var before = globe.globeScale
    mouseWheel(globe, 400, 300, 0, -120)
    var after = globe.globeScale
    verify(after < before, "Wheel input must zoom immediately")
    wait(250)
    compare(globe.globeScale, after, "The old button animation must stay stopped")
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner",
    ["-platform", "offscreen", "-import", directory, "-input", directory], {
      env: { ...process.env, QT_QUICK_BACKEND: "software",
        QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
      stdio: "inherit",
    })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Zoom control interaction tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
