import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const declaration = /\b\w+(?:\.\w+)*\s*\{\s*id\s*:\s*playerPanel\b/.exec(source)
assert.ok(declaration, "Could not find the production player panel")
const opening = source.indexOf("{", declaration.index)
let depth = 0
let closing = -1
// Ignore braces inside QML strings and comments while finding the object's end.
const tokens = /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\*[\s\S]*?\*\/|\/\/[^\n]*|[{}]/g
for (const token of source.slice(opening).matchAll(tokens)) {
  if (token[0] === "{") depth++
  if (token[0] === "}" && --depth === 0) {
    closing = opening + token.index + 1
    break
  }
}
assert.ok(closing > opening, "Could not find the end of the production player panel")
const panel = source.slice(declaration.index, closing)
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
assert.ok(fs.existsSync(path.join(shellDirectory, "Ui/Button.qml")),
  "Set OMARCHY_SHELL_DIR to an Omarchy checkout’s shell directory")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-player-layout-"))

try {
  // Use the real shell controls and style; stub only process, filesystem and compositor IO.
  fs.symlinkSync(path.resolve(shellDirectory), path.join(directory, "qs"))
  fs.cpSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"), { recursive: true })
  for (const [name, property] of [
    ["Process", "signal exited(int exitCode)"],
    ["FileView", "property bool atomicWrites: false"],
  ]) {
    const target = path.join(directory, "Quickshell/Io", name + ".qml")
    fs.writeFileSync(target, fs.readFileSync(target, "utf8").replace(/}\s*$/, property + "\n}"))
  }
  fs.copyFileSync(new URL("../BarWidget.qml", import.meta.url), path.join(directory, "RadioBar.qml"))
  fs.writeFileSync(path.join(directory, "tst_player_layout.qml"), `
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtTest
import qs.Ui
import qs.Commons

TestCase {
  id: root
  name: "PlayerLayout"
  width: 390
  height: 600
  visible: true
  when: windowShown
  property bool playerRunning: true
  property bool playerPaused: false
  property bool playerStopped: false
  property bool playerMuted: false
  property bool playerActionBusy: false
  property bool playPreparing: false
  property bool playCancellationRequested: false
  property bool randomPlaybackPending: false
  property int playerVolume: 100
  property int playlistCount: 20
  property string playingStationUuid: "station"
  property string playingStationName: "A long station name that must stay above the controls"
  property string playingTrackTitle: "A long track title that must stay above the controls"
  property string playerTitle: ""
  readonly property var playingTrackParts: ({ artist: "", title: playingTrackTitle })
  readonly property string trackCopyText: playingTrackTitle
  property bool trackCopied: false
  property string playingLogoPath: ""
  readonly property int edgeInset: Style.spacing.md
  function copyTrack() { trackCopied = true }
  property string playerError: ""
  property string streamError: ""
  property string playerOutput: ""
  property color foreground: "white"
  property color background: "black"
  property color accent: "cyan"
  property color urgent: "red"
  property color dim: "gray"
  property color faint: "#333333"
  property color favoriteColor: "yellow"
  property string lastAction: ""
  function isFavorite(uuid) { return false }
  function playerAction(action) { lastAction = action }
  function playSelected() { lastAction = "selected" }
  function stopPlayer() { lastAction = "stop"; randomPlaybackPending = false }
  QtObject { id: stopProcess; property bool running: false }
  QtObject { id: playerActionProcess; property bool running: false }
  QtObject { id: outputProcess; property bool running: false }

  QtObject {
    id: barHost
    property bool vertical: false
    property int barSize: 32
    property string fontFamily: Style.font.family
    property color barForeground: "white"
    property color urgent: "red"
    property bool foregroundAnimationEnabled: false
    function showTooltip() {}
    function hideTooltip() {}
    function registerClickTarget() {}
    function unregisterClickTarget() {}
  }
  RadioBar { id: barWidget; bar: barHost; visible: false; z: 10 }

  ${panel}

  function test_controlsFit_data() {
    return [
      { tag: "normal", panelWidth: 390, fontSize: 12, stacked: false },
      { tag: "normal-larger-font", panelWidth: 553, fontSize: 17, stacked: false },
      { tag: "small-window", panelWidth: 312, fontSize: 12, stacked: false, shortSlider: true },
      { tag: "small-window-larger-font", panelWidth: 442, fontSize: 17, stacked: false, shortSlider: true },
      { tag: "small-window-large-font", panelWidth: 624, fontSize: 24, stacked: false, shortSlider: true },
      { tag: "large-font-fixed-spacing", panelWidth: 312, fontSize: 24, spacingScaleWithFont: false, stacked: true },
      { tag: "expanded-again", panelWidth: 390, fontSize: 12, stacked: false }
    ]
  }

  function controlsIn(item) {
    var controls = []
    for (var i = 0; i < item.children.length; i++) {
      var child = item.children[i]
      if (child instanceof Button || child instanceof PanelSlider || child.text === "100%")
        controls.push(child)
      else
        controls = controls.concat(controlsIn(child))
    }
    return controls
  }

  function bounds(item) {
    var point = item.mapToItem(playerPanel, 0, 0)
    return { left: point.x, top: point.y,
      right: point.x + item.width, bottom: point.y + item.height }
  }

  function test_controlsFit(data) {
    width = data.panelWidth
    Style.fontBaseSize = data.fontSize
    Style.spacingScaleWithFont = data.spacingScaleWithFont !== false
    // Font changes can polish text before scheduling the containing layouts.
    verify(waitForPolish(root.Window.window), "Font and layout changes must settle before measuring")
    if (data.stacked) {
      verify(bounds(outputControls).top >= bounds(transportControls).bottom + Style.spacing.xs - 0.5,
        "Volume must move below playback when the window is narrow")
    } else {
      compare(bounds(outputControls).bottom, bounds(transportControls).bottom,
        "Normal windows must retain the single row")
      verify(Math.abs(muteButton.mapToItem(playerPanel, 0, 0).x - bounds(transportControls).right
          - Style.spacing.xs - Style.spacing.md) <= 0.5,
        "Separate the playback and volume groups with a wider gap")
      if (data.shortSlider)
        verify(volumeSlider.width < Style.space(116), "Shorten the slider before moving to two rows")
      else
        verify(volumeSlider.width >= Style.space(116), "Use spare width for the volume slider")
    }
    var controls = controlsIn(playerPanel)
    compare(controls.length, 8, "Favorite, six playback/output buttons, slider (percentage floats on hover)")
    verify(trackLine.visible && trackLine.text !== "", "Track metadata must be present")
    var status = playerStatus
    var statusBottom = bounds(status).bottom
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i]
      var label = control.tooltipText || control.Accessible.name || control.text
      var rect = bounds(control)
      verify(rect.left >= 0 && rect.right <= playerPanel.width + 0.5,
        label + " must fit horizontally")
      verify(rect.top >= 0 && rect.bottom <= playerPanel.height + 0.5,
        label + " must fit vertically")
      if (control !== playingFavoriteButton)
        verify(rect.top >= statusBottom + Style.spacing.md - 0.5,
          label + " must stay below station metadata")
      for (var j = 0; j < i; j++) {
        var other = bounds(controls[j])
        verify(rect.right <= other.left + 0.5 || rect.left >= other.right - 0.5
          || rect.bottom <= other.top + 0.5 || rect.top >= other.bottom - 0.5,
          label + " overlaps " + (controls[j].tooltipText || controls[j].Accessible.name || controls[j].text))
      }
      if (control.text === "100%")
        verify(control.width >= control.implicitWidth - 0.5, "The percentage must not clip")
    }
    verify(volumeSlider.width >= volumeSlider.knobSize * 2, "Keep a usable volume track")
    var iconButtons = transportControls.children
      .filter(function(item) { return item instanceof Button && item.visible })
    for (var k = 0; k < iconButtons.length; k++)
      compare(iconButtons[k].width, iconButtons[0].width, "Transport buttons share one width")
    var muteWidth = muteButton.width
    playerMuted = !playerMuted
    waitForPolish(outputControls)
    compare(muteButton.width, muteWidth, "Mute must not change width")
    playerMuted = !playerMuted
    var playButton = transportControls.children[1]
    var playWidth = playButton.width
    playerPaused = !playerPaused
    waitForPolish(transportControls)
    compare(playButton.width, playWidth, "Play/pause must not change width")
    playerPaused = !playerPaused
  }

  function test_logoAndPercentFit_data() {
    return [
      { tag: "small-window-hover", panelWidth: 312, fontSize: 12, drag: false },
      { tag: "small-window-drag", panelWidth: 312, fontSize: 12, drag: true },
      { tag: "large-font-hover", panelWidth: 312, fontSize: 24, spacingScaleWithFont: false, drag: false },
      { tag: "large-font-drag", panelWidth: 624, fontSize: 24, drag: true }
    ]
  }

  function test_logoAndPercentFit(data) {
    width = data.panelWidth
    Style.fontBaseSize = data.fontSize
    Style.spacingScaleWithFont = data.spacingScaleWithFont !== false
    playerStopped = false
    playingLogoPath = Qt.resolvedUrl("logo.png")
    tryCompare(stationLogoImage, "status", Image.Ready)
    verify(stationLogo.visible, "A loaded local logo must be shown")
    if (data.drag) volumeSlider.dragging = true
    else mouseMove(volumeSlider, volumeSlider.width / 2, volumeSlider.height / 2)
    tryCompare(volumePercent, "visible", true)
    verify(waitForPolish(root.Window.window), "Logo and layout changes must settle before measuring")
    var items = [stationLogo, nowPlaying, playerStatus, trackLine, volumePercent, volumeSlider]
    for (var i = 0; i < items.length; i++) {
      var rect = bounds(items[i])
      verify(rect.left >= -0.5 && rect.right <= playerPanel.width + 0.5, "item " + i + " must fit horizontally")
      verify(rect.top >= -0.5 && rect.bottom <= playerPanel.height + 0.5, "item " + i + " must fit vertically")
    }
    var logo = bounds(stationLogo)
    verify(bounds(nowPlaying).left >= logo.right - 0.5, "Station name must start after the logo")
    verify(bounds(volumePercent).bottom <= bounds(volumeSlider).top + 0.5, "Percentage floats above the slider")
    volumeSlider.dragging = false
    mouseMove(playerPanel, 1, 1)
    playingLogoPath = ""
  }

  function test_playerState_data() {
    return [
      { tag: "live", paused: false, stopped: false, error: "",
        status: "Live", action: "Pause", icon: "\\uf04c", active: true, tooltip: "Playing:" },
      { tag: "paused", paused: true, stopped: false, error: "",
        status: "Paused", action: "Play", icon: "\\uf04b", active: false, tooltip: "Radio paused:" },
      { tag: "external-stop", paused: false, stopped: true, error: "",
        status: "Stopped", action: "Play", icon: "\\uf04b", active: false, tooltip: "Radio stopped" },
      { tag: "stream-failed", paused: true, stopped: false, error: "Stream disconnected",
        status: "Stream disconnected. Play to retry, or Next.", action: "Retry station",
        icon: "\\uf04b", active: false, tooltip: "Stream disconnected:" }
    ]
  }

  function test_stopCanCancelRandomBeforePlaybackStarts() {
    playerRunning = false
    playPreparing = false
    randomPlaybackPending = false
    var stopButton = transportControls.children[3]
    compare(stopButton.enabled, false)
    randomPlaybackPending = true
    compare(stopButton.enabled, true)
    lastAction = ""
    mouseClick(stopButton)
    compare(lastAction, "stop")
    compare(randomPlaybackPending, false)
    compare(stopButton.enabled, false)
  }

  function test_barRightClick_data() {
    return [
      { tag: "playing", running: true, paused: false, stopped: false, action: "stop" },
      { tag: "paused", running: true, paused: true, stopped: false, action: "stop" },
      { tag: "externally-stopped", running: true, paused: false, stopped: true, action: "toggle" },
      { tag: "player-exited", running: false, paused: false, stopped: false, action: "resume" }
    ]
  }

  property real initialFontBaseSize: 0
  property bool initialSpacingScaleWithFont: true

  function initTestCase() {
    initialFontBaseSize = Style.fontBaseSize
    initialSpacingScaleWithFont = Style.spacingScaleWithFont
  }

  function cleanup() {
    // Layout rows change global Style; restore it so later tests start clean.
    Style.fontBaseSize = initialFontBaseSize
    Style.spacingScaleWithFont = initialSpacingScaleWithFont
    for (var i = 0; i < barWidget.resources.length; i++) {
      var resource = barWidget.resources[i]
      if (resource.command !== undefined) resource.running = false
    }
    barWidget.visible = false
  }

  function test_barRightClick(data) {
    barWidget.applyPlayerState(JSON.stringify(data))
    barWidget.visible = true
    var button = barWidget.children.find(function(item) { return item instanceof WidgetButton })
    mouseClick(button, button.width / 2, button.height / 2, Qt.RightButton)
    var process = barWidget.resources.find(function(item) {
      return item.command && item.command[1] === data.action
    })
    verify(process !== undefined, "Right click must dispatch " + data.action)
    compare(process.running, true)
  }

  function test_playerState(data) {
    playerRunning = true
    playerPaused = data.paused
    playerStopped = data.stopped
    streamError = data.error
    lastAction = ""
    barWidget.applyPlayerState(JSON.stringify({
      running: true, paused: data.paused, stopped: data.stopped, error: data.error,
      title: playingStationName, volume: playerVolume
    }))
    var playButton = transportControls.children[1]
    var barButton = barWidget.children.find(function(item) { return item instanceof WidgetButton })
    verify(playerStatus.text.indexOf(data.status) >= 0)
    compare(playButton.tooltipText, data.action)
    compare(playButton.iconText, data.icon)
    compare(barButton.active, data.active)
    verify(barButton.tooltipText.indexOf(data.tooltip) === 0)
    if (data.stopped) compare(nowPlaying.text, "Nothing playing")
    else compare(nowPlaying.text, playingStationName)
    mouseClick(playButton)
    compare(lastAction, "toggle", "Play after external Stop must resume the existing player")
  }
}
`)
  fs.writeFileSync(path.join(directory, "logo.png"), Buffer.from(
    "89504e470d0a1a0a0000000d4948445200000004000000040806000000a9f19e7e0000001249444154789c63f8dfc0f01f1933902e0000504f27e1eb00f8a50000000049454e44ae426082", "hex"))
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-import", directory, "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software",
      QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Player layout tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
