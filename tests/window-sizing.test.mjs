import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { linkShellUi } from "./shell-fixture.mjs"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const sizing = source.slice(source.indexOf("  property bool windowFrameReady"),
  source.indexOf("  readonly property string windowPath"))
const lifecycle = source.match(/  function (?:registerWindowSetup|open|openWindow|close|dismiss|scheduleWindowReveal)\([\s\S]*?\n  \}/g).join("\n")
const setup = source.match(/  Process \{\n    id: windowSetupProcess[\s\S]*?\n  \}/)[0]
const revealTimer = source.match(/  Timer \{\n    id: windowRevealTimer[\s\S]*?\n  \}/)[0]
const windowSignals = source.match(/    onVisibleChanged: \{[\s\S]*?(?=\n\n    BorderSurface)/)[0]
const minimumSize = source.match(/    minimumSize: (.*)/)[1]
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-window-sizing-"))

try {
  const bin = path.join(directory, "bin")
  fs.mkdirSync(bin)
  fs.writeFileSync(path.join(bin, "hyprctl"), `#!/bin/sh
if [ "$1" = "-j" ]; then
  printf '{"configProvider":"%s"}\\n' "$RADIO_ATLAS_TEST_WINDOW_PROVIDER"
  exit 0
fi
printf '%s\\n' "$RADIO_ATLAS_TEST_WINDOW_EVAL"
`, { mode: 0o755 })
  for (const [provider, response, exitCode] of [["lua", "ok", 0], ["lua", "rule rejected", 1], ["hyprlang", "", 2]]) {
    const result = spawnSync(fileURLToPath(new URL("../radio-window", import.meta.url)), ["1068", "672"], {
      env: { ...process.env, PATH: bin + path.delimiter + process.env.PATH,
        RADIO_ATLAS_TEST_WINDOW_PROVIDER: provider, RADIO_ATLAS_TEST_WINDOW_EVAL: response },
      encoding: "utf8",
    })
    if (result.error) throw result.error
    assert.equal(result.status, exitCode, result.stderr)
  }
  linkShellUi(directory, shellDirectory)
  fs.cpSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"), { recursive: true })
  const hyprland = path.join(directory, "Quickshell/Hyprland/Hyprland.qml")
  fs.writeFileSync(hyprland, fs.readFileSync(hyprland, "utf8").replace(/}\s*$/, `
    property var focusedMonitor: null
    property var windowMonitor: null
    function monitorFor(screen) { return windowMonitor || focusedMonitor }
    function refreshMonitors() {}
  }`))
  const quickshell = path.join(directory, "Quickshell/Quickshell.qml")
  fs.writeFileSync(quickshell, fs.readFileSync(quickshell, "utf8").replace(/}\s*$/, "property var screens: []\n}"))
  fs.writeFileSync(path.join(directory, "tst_window_sizing.qml"), `
import QtQuick
import QtTest
import qs.Commons
import Quickshell
import Quickshell.Hyprland

TestCase {
  id: root
  name: "WindowSizing"
  ${sizing}
  property string windowPath: "/fixture/radio-window"
  property bool opened: false
  property bool helpVisible: false
  property bool outputMenuOpen: false
  property var manifest: null
  property int dismissals: 0
  property var shell: QtObject {
    function hide(id) { root.dismissals++ }
  }
  property var startedCommands: []
  property var shownSizes: []
  property int worldExpansionMisses: 0
  property var worldStations: [{}]
  property string fetchError: ""
  property int randomRequests: 0
  function loadState() {
    shownSizes = shownSizes.concat([{ width: preferredWidth, height: preferredHeight }])
  }
  function showWorld() {}
  function tuneRandom() { randomRequests++ }
  function scheduleWorldExpansion(delay) {}
  ${lifecycle}
  ${setup.replace("Process {", "QtObject {").replace("    command:", `    property bool running: false
    signal exited(int exitCode)
    onRunningChanged: if (running) root.startedCommands = root.startedCommands.concat([command.slice()])
    property var command:`)}
  QtObject {
    id: panel
    property bool visible: false
    property bool backingWindowVisible: visible
    property var screen: null
    property size minimumSize: ${minimumSize}
    property int width: root.preferredWidth
    property int height: root.preferredHeight
    property real opacity: root.windowFrameReady ? 1 : 0
    ${windowSignals}
  }
  Item { id: keyCatcher }
  QtObject { id: globe; function stopKineticRotation(clear) {} }
  QtObject { id: worldExpandProcess; property bool running: false }
  Timer { id: worldExpandTimer }
  ${revealTimer}

  function monitor(width, height, scale, transform, reserved) {
    return { width: width, height: height, scale: scale,
      name: "fixture", lastIpcObject: { transform: transform || 0, reserved: reserved || [0, 0, 0, 0] } }
  }
  function focusMonitor(value) {
    Hyprland.focusedMonitor = value
    Quickshell.screens = value ? [{ name: value.name,
      width: Math.floor((value.lastIpcObject.transform % 2 ? value.height : value.width) / value.scale),
      height: Math.floor((value.lastIpcObject.transform % 2 ? value.width : value.height) / value.scale) }] : []
  }
  function finishSetup(exitCode) {
    panel.screen = Quickshell.screens[0] || null
    windowSetupProcess.running = false
    windowSetupProcess.exited(exitCode === undefined ? 0 : exitCode)
  }
  function init() {
    close()
    windowSetupProcess.running = false
    pendingOpenPayload = ""
    startedCommands = []
    shownSizes = []
    dismissals = 0
    randomRequests = 0
    Hyprland.windowMonitor = null
    focusMonitor(monitor(1920, 1080, 1))
    Style.fontBaseSize = 12
    Style.spacingScale = 1
    Style.spacingScaleWithFont = true
  }

  function test_fit_data() {
    return [
      { tag: "desktop", monitor: monitor(1920, 1080, 1), width: 1180, height: 760 },
      { tag: "laptop-2x", monitor: monitor(2256, 1504, 2), width: 1068, height: 672 },
      { tag: "small-2x", monitor: monitor(1920, 1080, 2), width: 900, height: 460 },
      { tag: "fractional-scale", monitor: monitor(1920, 1080, 1.5), width: 1180, height: 640 },
      { tag: "below-old-minimum", monitor: monitor(640, 512, 1), width: 580, height: 432 },
      { tag: "portrait", monitor: monitor(1920, 1080, 2, 1), width: 480, height: 760 },
      { tag: "portrait-flipped", monitor: monitor(1920, 1080, 2, 7), width: 480, height: 760 },
      { tag: "reserved-top-bottom", monitor: monitor(2256, 1504, 2, 0, [0, 90, 0, 50]), width: 1068, height: 572 },
      { tag: "reserved-sides", monitor: monitor(2256, 1504, 2, 0, [100, 0, 50, 26]), width: 938, height: 672 },
      { tag: "no-monitor", monitor: null, width: 1180, height: 760 }
    ]
  }
  function test_fit(data) {
    focusMonitor(data.monitor)
    compare(preferredWidth, data.width)
    compare(preferredHeight, data.height)
    compare(panel.minimumSize.width, Math.min(800, data.width))
    compare(panel.minimumSize.height, Math.min(560, data.height))
  }
  function test_reopenRefreshesRule() {
    registerWindowSetup()
    finishSetup()
    focusMonitor(monitor(2256, 1504, 2))
    open('{"action":"random"}')
    compare(panel.visible, false, "Wait for the current size rule before mapping")
    compare(startedCommands.length, 2)
    compare(startedCommands[1][1], "1068")
    compare(startedCommands[1][2], "672")
    finishSetup()
    compare(shownSizes.length, 1)
    compare(randomRequests, 1)
  }
  function test_summonWhileOpenKeepsWindowVisible_data() {
    return [{ tag: "revealed", waitForReveal: true },
      { tag: "reveal-pending", waitForReveal: false }]
  }
  function test_summonWhileOpenKeepsWindowVisible(data) {
    open("{}")
    finishSetup()
    if (data.waitForReveal) tryCompare(panel, "opacity", 1)
    open('{"action":"random"}')
    finishSetup()
    compare(randomRequests, 1)
    if (data.waitForReveal) compare(panel.opacity, 1, "An open window must not flash hidden")
    tryCompare(panel, "opacity", 1, 200)
  }
  function test_monitorChangesDuringSetup() {
    open("{}")
    focusMonitor(monitor(1920, 1080, 2))
    finishSetup()
    compare(shownSizes.length, 0, "Do not open using the previous monitor's rule")
    compare(startedCommands.length, 2)
    compare(startedCommands[1][1], "900")
    compare(startedCommands[1][2], "460")
    finishSetup()
    compare(shownSizes.length, 1)
  }
  function test_closeCancelsPendingOpen() {
    open("{}")
    close()
    finishSetup()
    compare(shownSizes.length, 0)
    compare(panel.visible, false)
  }
  function test_setupFailureCancelsOpenAndAllowsRetry_data() {
    return [{ tag: "lua-rule-rejected", code: 1, changeMonitor: false },
      { tag: "failure-after-monitor-change", code: 127, changeMonitor: true }]
  }
  function test_setupFailureCancelsOpenAndAllowsRetry(data) {
    open("{}")
    if (data.changeMonitor) focusMonitor(monitor(2256, 1504, 2))
    finishSetup(data.code)
    compare(shownSizes.length, 0)
    compare(pendingOpenPayload, "")
    compare(windowSetupProcess.running, false, "Failures must not retry in a loop")
    compare(dismissals, 1, "Clear the shell's active panel so the next click can retry")
    open("{}")
    finishSetup()
    compare(shownSizes.length, 1)
  }
  function test_nonLuaSetupKeepsExistingFallback() {
    open("{}")
    finishSetup(2)
    compare(shownSizes.length, 1)
    compare(dismissals, 0)
  }
  function test_qtGeometryWinsOverStaleMonitorScale() {
    focusMonitor(monitor(2256, 1504, 1))
    Quickshell.screens = [{ name: "fixture", width: 1128, height: 752 }]
    compare(preferredWidth, 1068)
    compare(preferredHeight, 672)
  }
  function test_mappedWindowUsesOwnMonitor() {
    Hyprland.windowMonitor = monitor(1920, 1080, 2)
    panel.screen = { name: "other", width: 960, height: 540 }
    panel.visible = true
    compare(preferredWidth, 900)
    compare(preferredHeight, 460)
    focusMonitor(monitor(640, 512, 1))
    compare(preferredWidth, 900, "Focusing another display must not change this window's sizing")
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-import", directory, "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software", QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Window sizing tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
