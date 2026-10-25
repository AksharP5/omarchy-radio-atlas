import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { linkShellUi } from "./shell-fixture.mjs"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const card = source.match(/    BorderSurface \{[\s\S]*?(?=      Item \{\n        id: header)/)[0]
  .replace("BorderSurface {", "Item {")
  .replace(/^      (color|borderSpec|radius):.*\n/gm, "")
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
const outputMenu = source.match(/          MouseArea \{\n            visible: root.outputMenuOpen[\s\S]*?(?=\n        \}\n      \}\n\n      Flickable)/)?.[0]
assert.ok(outputMenu, "Could not find the production output menu")
const outputFunctions = source.match(/  function (?:refreshOutputs|toggleOutputMenu|setAudioOutputs)\([\s\S]*?\n  \}/g).join("\n")
const outputsComplete = source.match(/id: outputsProcess[\s\S]*?onExited: function\(exitCode\) \{([\s\S]*?)\n    \}\n  \}/)[1]
const localPaths = source.match(/^  readonly property string (?:fetchPath|playerPath|statePath|windowPath):[^\n]*(?:\n    [^\n]+)?/gm)
const countriesPath = source.match(/    path: ([^\n]*countries\.json[^\n]*)/)[1]
const countryNamesPath = source.match(/    path: ([^\n]*country-search\.json[^\n]*)/)[1]
const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
assert.ok(fs.existsSync(path.join(shellDirectory, "Ui/Button.qml")),
  "Set OMARCHY_SHELL_DIR to an Omarchy checkout’s shell directory")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-player-layout-%25 # ?-"))

try {
  // Use the real shell controls and style; stub only process, filesystem and compositor IO.
  linkShellUi(directory, shellDirectory)
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
import QtQuick.Controls as QQC
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
  ${localPaths.join("\n")}
  property string countriesPath: ${countriesPath}
  property string countryNamesPath: ${countryNamesPath}
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
  property bool helpVisible: false
  property bool outputMenuOpen: false
  property var audioOutputs: []
  property string outputsError: ""
  property string lastOutput: ""
  readonly property var outputChoices: [{ id: "", label: "System default" }].concat(audioOutputs)
  function outputLabel(sink) { return sink }
  ${outputFunctions}
  function selectOutput(sink) { lastOutput = sink; outputMenuOpen = false }
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
  function isHelpKey(event) { return event.key === Qt.Key_Question }
  function dismiss() { lastAction = "dismiss" }
  QtObject { id: stopProcess; property bool running: false }
  QtObject { id: playerActionProcess; property bool running: false }
  QtObject { id: outputProcess; property bool running: false }
  QtObject {
    id: outputsProcess
    property bool running: false
    property var command: []
    property string output: ""
    property string errorOutput: ""
    signal exited(int exitCode)
    onExited: function(exitCode) { ${outputsComplete} }
  }

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

  Rectangle { anchors.fill: parent; color: root.background }
  ${card}
    TextInput { id: searchField }
    Item {
      id: sidebar
      anchors.fill: parent
      ${panel}
      ${outputMenu}
    }
  }

  function test_localPaths() {
    var directory = ${JSON.stringify(directory)}
    compare(fetchPath, directory + "/radio-fetch")
    compare(playerPath, directory + "/radio-player")
    compare(statePath, directory + "/radio-state")
    compare(windowPath, directory + "/radio-window")
    compare(countriesPath, directory + "/assets/countries.json")
    compare(countryNamesPath, directory + "/assets/country-search.json")
    compare(barWidget.playerPath, playerPath)
  }

  function test_controlsFit_data() {
    return [
      { tag: "normal", panelWidth: 390, fontSize: 12, stacked: false },
      { tag: "normal-larger-font", panelWidth: 553, fontSize: 17, stacked: false },
      { tag: "small-window", panelWidth: 312, fontSize: 12, stacked: false, shortSlider: true },
      { tag: "small-window-larger-font", panelWidth: 442, fontSize: 17, stacked: false, shortSlider: true },
      { tag: "small-window-large-font", panelWidth: 624, fontSize: 24, stacked: false, shortSlider: true },
      // Fallback icon fonts can still fit one row at 312 px; force wrapping here.
      { tag: "large-font-fixed-spacing", panelWidth: 250, fontSize: 24, spacingScaleWithFont: false, stacked: true },
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

  function test_controlsWrapWithoutFeedback() {
    width = 1000
    Style.fontBaseSize = 17
    verify(waitForPolish(root.Window.window))
    var minimumWidth = transportControls.implicitWidth + outputControls.implicitWidth
      - volumeSlider.Layout.preferredWidth + volumeSlider.Layout.minimumWidth
      + playerControls.columnSpacing + root.edgeInset * 2
    // Exercise the gap where a column-dependent child margin used to toggle wrapping.
    var narrowWidth = Math.floor(minimumWidth - Style.spacing.md / 2)
    width = narrowWidth
    verify(waitForPolish(root.Window.window), "Wrapping must settle below the single-row minimum")
    compare(playerControls.columns, 1)
    verify(bounds(outputControls).top >= bounds(transportControls).bottom + Style.spacing.xs - 0.5)
    width = Math.ceil(minimumWidth + 1)
    verify(waitForPolish(root.Window.window))
    compare(playerControls.columns, 2)
    width = narrowWidth
    verify(waitForPolish(root.Window.window), "Shrinking again must settle on two rows")
    compare(playerControls.columns, 1)
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

  function test_outputMenuFits_data() {
    return [
      { tag: "laptop", panelWidth: 390, panelHeight: 626, fontSize: 12, outputs: 20 },
      // The sidebar inside an 875x427 window, below its 65px header.
      { tag: "short-large-font", panelWidth: 341, panelHeight: 362, fontSize: 17, outputs: 20 },
      { tag: "short-no-other-outputs", panelWidth: 341, panelHeight: 362, fontSize: 17, outputs: 0 }
    ]
  }

  function chooseOutput(index, expected) {
    outputList.positionViewAtIndex(index, ListView.Contain)
    verify(waitForPolish(root.Window.window))
    var option = outputList.itemAtIndex(index)
    verify(option !== null, "The selected output must be instantiated")
    var point = option.mapToItem(root, option.width / 2, option.height / 2)
    verify(point.y >= 0 && point.y < height, "The output must be reachable in the window")
    lastOutput = "pending"
    mouseClick(option)
    compare(lastOutput, expected)
    compare(outputMenuOpen, false)
    outputMenuOpen = true
    verify(waitForPolish(root.Window.window))
  }

  function test_outputMenuFits(data) {
    width = data.panelWidth
    height = data.panelHeight
    Style.fontBaseSize = data.fontSize
    audioOutputs = Array.from({ length: data.outputs }, function(_, i) {
      return { id: "sink-" + i, label: "Output " + (i + 1) }
    })
    outputMenuOpen = true
    verify(waitForPolish(root.Window.window))
    verify(outputMenu.y >= 0, "The output menu must stay below the window header")
    verify(outputMenu.x >= 0 && outputMenu.x + outputMenu.width <= width)
    verify(outputMenu.y + outputMenu.height <= outputMenu.buttonPosition.y,
      "The output menu must stay above its button")
    verify(outputList.height > 0)
    if (data.tag === "laptop") compare(outputList.height, Style.space(320))
    chooseOutput(0, "")
    if (data.outputs === 0) return
    chooseOutput(1, "sink-0")
    chooseOutput(data.outputs, "sink-" + (data.outputs - 1))
    verify(outputList.contentY > 0, "The last output must be reached by scrolling")
  }

  function test_outputKeyboardScrolls() {
    width = 341
    height = 362
    Style.fontBaseSize = 17
    audioOutputs = Array.from({ length: 20 }, function(_, i) {
      return { id: "sink-" + i, label: "Output " + (i + 1) }
    })
    outputMenuOpen = true
    verify(waitForPolish(root.Window.window))
    outputButton.forceActiveFocus()
    for (var i = 0; i < outputChoices.length; i++) {
      keyClick(Qt.Key_Tab)
      verify(waitForPolish(root.Window.window))
      verify(waitForRendering(outputList))
      var option = outputList.itemAtIndex(i)
      verify(option !== null && option.activeFocus, "Tab must reach output " + i)
      var point = option.mapToItem(outputList, 0, 0)
      verify(point.y >= -0.5 && point.y + option.height <= outputList.height + 0.5,
        "Focused output " + i + " must be visible; y=" + point.y + ", height=" + outputList.height)
    }
    keyClick(Qt.Key_Return)
    compare(lastOutput, "sink-19")
    outputMenuOpen = true
    verify(waitForPolish(root.Window.window))
    outputList.itemAtIndex(20).forceActiveFocus()
    for (var i = 19; i >= 0; i--) {
      keyClick(Qt.Key_Tab, Qt.ShiftModifier)
      verify(waitForPolish(root.Window.window))
      verify(waitForRendering(outputList))
      var option = outputList.itemAtIndex(i)
      verify(option !== null && option.activeFocus, "Shift+Tab must reach output " + i)
      var point = option.mapToItem(outputList, 0, 0)
      verify(point.y >= -0.5 && point.y + option.height <= outputList.height + 0.5,
        "Focused output " + i + " must remain visible when navigating upward")
    }
    keyClick(Qt.Key_Space)
    compare(lastOutput, "")
  }

  function test_closedOutputMenuReleasesKeyboard_data() {
    return [{ tag: "keyboard" }, { tag: "pointer" }, { tag: "outside-click" }, { tag: "escape" }]
  }

  function test_closedOutputMenuReleasesKeyboard(data) {
    width = 390
    playerRunning = true
    audioOutputs = [{ id: "sink", label: "Test output" }]
    outputMenuOpen = true
    verify(waitForPolish(root.Window.window))
    outputButton.forceActiveFocus()
    keyClick(Qt.Key_Tab)
    keyClick(Qt.Key_Tab)
    var option = outputList.itemAtIndex(1)
    verify(option.activeFocus)
    if (data.tag === "keyboard") keyClick(Qt.Key_Return)
    else if (data.tag === "pointer") mouseClick(option)
    else if (data.tag === "outside-click") mouseClick(sidebar, 1, 1)
    else keyClick(Qt.Key_Escape)
    compare(outputMenuOpen, false)
    lastOutput = "unchanged"
    lastAction = ""
    keyClick(Qt.Key_Space)
    compare(lastAction, "toggle", "Space must reach playback after the menu closes")
    keyClick(Qt.Key_Return)
    compare(lastAction, "selected", "Enter must play the selected station")
    compare(lastOutput, "unchanged", "Hidden output choices must not consume playback keys")
  }

  function test_closingOutputMenuPreservesSearchFocus() {
    outputMenuOpen = true
    searchField.forceActiveFocus()
    outputMenuOpen = false
    verify(searchField.activeFocus)
  }

  function test_outputRefreshPreservesKeyboardChoice_data() {
    return [
      { tag: "unchanged", change: "none", index: 1 },
      { tag: "new-device", change: "add", index: 1 },
      { tag: "reordered-and-renamed", change: "reorder", index: 2 }
    ]
  }

  function test_outputRefreshPreservesKeyboardChoice(data) {
    width = 390
    height = 626
    audioOutputs = [{ id: "speaker-a", label: "Speaker A" }, { id: "speaker-b", label: "Speaker B" }]
    toggleOutputMenu()
    verify(outputsProcess.running)
    verify(waitForPolish(root.Window.window))
    outputButton.forceActiveFocus()
    keyClick(Qt.Key_Tab)
    keyClick(Qt.Key_Tab)
    verify(outputList.itemAtIndex(1).activeFocus)
    var refreshed = data.change === "reorder"
      ? [{ id: "speaker-b", label: "Speaker B" }, { id: "speaker-a", label: "Renamed A" }]
      : data.change === "add" ? audioOutputs.concat([{ id: "speaker-c", label: "Speaker C" }])
      : audioOutputs
    outputsProcess.output = JSON.stringify({ outputs: refreshed })
    outputsProcess.running = false
    outputsProcess.exited(0)
    tryVerify(function() {
      var option = outputList.itemAtIndex(data.index)
      return option !== null && option.activeFocus
    }, 1000, "Refreshing outputs must keep focus on Speaker A")
    lastOutput = "unchanged"
    keyClick(Qt.Key_Return)
    compare(lastOutput, "speaker-a", "Enter must choose the speaker focused before refresh")
  }

  function test_outputRefreshRemovesFocusedSpeaker_data() {
    return [
      { tag: "removed", exitCode: 0, output: '{"outputs":[]}', error: "" },
      { tag: "command-failed", exitCode: 3, output: "", error: "Audio outputs are unavailable" },
      { tag: "invalid-response", exitCode: 0, output: "{", error: "Audio outputs are unavailable" }
    ]
  }

  function test_outputRefreshRemovesFocusedSpeaker(data) {
    audioOutputs = [{ id: "speaker-a", label: "Speaker A" }]
    toggleOutputMenu()
    verify(waitForPolish(root.Window.window))
    outputList.itemAtIndex(1).forceActiveFocus()
    outputsProcess.output = data.output
    outputsProcess.running = false
    outputsProcess.exited(data.exitCode)
    compare(audioOutputs.length, 0)
    compare(outputsError, data.error)
    tryVerify(function() { return outputButton.activeFocus }, 1000)
    lastOutput = "unchanged"
    keyClick(Qt.Key_Return)
    compare(lastOutput, "unchanged", "A missing speaker must not become a different output selection")
    compare(outputMenuOpen, false)
  }

  function test_outputRefreshAfterFocusMoves_data() {
    return [{ tag: "search", close: false }, { tag: "closed", close: true }]
  }

  function test_outputRefreshAfterFocusMoves(data) {
    audioOutputs = [{ id: "speaker-a", label: "Speaker A" }]
    toggleOutputMenu()
    verify(waitForPolish(root.Window.window))
    outputList.itemAtIndex(1).forceActiveFocus()
    if (data.close) outputMenuOpen = false
    else searchField.forceActiveFocus()
    outputsProcess.output = JSON.stringify({ outputs: audioOutputs })
    outputsProcess.running = false
    outputsProcess.exited(0)
    wait(0)
    if (data.close) verify(keyCatcher.activeFocus)
    else verify(searchField.activeFocus)
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
    outputMenuOpen = false
    outputsProcess.running = false
    audioOutputs = []
    Style.fontBaseSize = initialFontBaseSize
    Style.spacingScaleWithFont = initialSpacingScaleWithFont
    height = 600
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

  function test_barCancelsPendingResume_data() {
    return [
      { tag: "preparing", running: false },
      { tag: "player-started", running: true }
    ]
  }

  function test_barCancelsPendingResume(data) {
    barWidget.applyPlayerState(JSON.stringify({ running: false }))
    barWidget.visible = true
    var button = barWidget.children.find(function(item) { return item instanceof WidgetButton })
    mouseClick(button, button.width / 2, button.height / 2, Qt.RightButton)
    var resume = barWidget.resources.find(function(item) {
      return item.command && item.command[1] === "resume" && item.running
    })
    verify(resume !== undefined, "Right click must begin Resume")
    barWidget.applyPlayerState(JSON.stringify({ running: data.running }))
    mouseClick(button, button.width / 2, button.height / 2, Qt.RightButton)
    var stop = barWidget.resources.find(function(item) {
      return item.command && item.command[1] === "stop" && item.running
    })
    verify(stop !== undefined, "A second right click must cancel the pending Resume")
  }

  function test_barVolumeCompletionKeepsLatestStatus() {
    var process = barWidget.resources.find(function(item) { return item.submittedVolume !== undefined })
    process.running = false
    barWidget.pendingVolume = -1
    barWidget.applyPlayerState(JSON.stringify({ running: true, volume: 70 }))
    barWidget.changeVolume(5)
    compare(process.submittedVolume, 75)
    barWidget.applyPlayerState(JSON.stringify({ running: true, volume: 80 }))
    compare(barWidget.reportedVolume, 80)
    process.running = false
    process.exited(0)
    compare(barWidget.pendingVolume, -1)
    compare(barWidget.playerVolume, 80, "An older command completion must preserve the latest player volume")
    compare(barWidget.reportedVolume, 80)
  }

  function test_barWheel_data() {
    return [
      { tag: "horizontal-right", x: 120, y: 0, volume: 70 },
      { tag: "horizontal-left", x: -120, y: 0, volume: 70 },
      { tag: "volume-up", x: 0, y: 120, volume: 75 },
      { tag: "volume-down", x: 0, y: -120, volume: 65 }
    ]
  }

  function test_barWheel(data) {
    var process = barWidget.resources.find(function(item) { return item.submittedVolume !== undefined })
    process.running = false
    barWidget.pendingVolume = -1
    barWidget.applyPlayerState(JSON.stringify({ running: true, volume: 70 }))
    barWidget.visible = true
    var button = barWidget.children.find(function(item) { return item instanceof WidgetButton })
    mouseWheel(button, button.width / 2, button.height / 2, data.x, data.y)
    compare(barWidget.playerVolume, data.volume)
    compare(process.running, data.y !== 0, "Only vertical scrolling may submit a volume change")
    if (data.y !== 0) compare(process.command[2], String(data.volume))
    else compare(barWidget.pendingVolume, -1)
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
