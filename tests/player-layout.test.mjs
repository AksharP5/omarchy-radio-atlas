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
  fs.symlinkSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"))
  fs.writeFileSync(path.join(directory, "tst_player_layout.qml"), `
import QtQuick
import QtQuick.Layouts
import QtTest
import qs.Ui
import qs.Commons

TestCase {
  id: root
  name: "PlayerLayout"
  width: 390
  height: 600
  when: windowShown
  property bool playerRunning: true
  property bool playerPaused: false
  property bool playerMuted: false
  property bool playerActionBusy: false
  property bool playPreparing: false
  property bool playCancellationRequested: false
  property int playerVolume: 100
  property int playlistCount: 20
  property string playingStationUuid: "station"
  property string playingStationName: "A long station name that must stay above the controls"
  property string playingTrackTitle: "A long track title that must stay above the controls"
  property string playerTitle: ""
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
  function isFavorite(uuid) { return false }
  QtObject { id: stopProcess; property bool running: false }
  QtObject { id: playerActionProcess; property bool running: false }
  QtObject { id: outputProcess; property bool running: false }

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
    waitForPolish(playerControls)
    waitForPolish(outputControls)
    if (data.stacked) {
      verify(bounds(outputControls).top >= bounds(transportControls).bottom + Style.spacing.xs - 0.5,
        "Volume must move below playback when the window is narrow")
    } else {
      compare(bounds(outputControls).bottom, bounds(transportControls).bottom,
        "Normal windows must retain the single row")
      verify(bounds(outputControls).left >= bounds(transportControls).right + Style.spacing.xs - 0.5,
        "Volume must remain to the right of playback")
      if (data.shortSlider)
        verify(volumeSlider.width < Style.space(116), "Shorten the slider before moving to two rows")
      else
        compare(volumeSlider.width, Style.space(116), "Keep the normal slider width")
    }
    var controls = controlsIn(playerPanel)
    compare(controls.length, 9, "Favorite, six playback/output buttons, slider, percentage")
    var status = playerPanel.children.find(function(item) {
      return item.text && item.text.indexOf(root.playingTrackTitle) === 0
    })
    verify(status !== undefined, "Track metadata must be present")
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
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-import", directory, "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Player layout tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
