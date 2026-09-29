import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const panel = source.match(/          Rectangle \{\n            id: playerPanel[\s\S]*?\n          \}/)?.[0]
assert.ok(panel, "Could not find the production player panel")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-player-layout-"))

try {
  fs.writeFileSync(path.join(directory, "tst_player_layout.qml"), `
import QtQuick
import QtQuick.Layouts
import QtTest

TestCase {
  id: root
  name: "PlayerLayout"
  width: 390
  height: 600
  when: windowShown
  property int baseFontSize: 12
  property bool spacingScaleWithFont: true
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

  // Shell components are unavailable in CI. Keep their font/padding sizing;
  // all placement and available-space decisions come from the production panel.
  QtObject {
    id: style
    function space(value) {
      return Math.round(value * (root.spacingScaleWithFont ? root.baseFontSize / 12 : 1))
    }
    property QtObject spacing: QtObject {
      property int xs: style.space(3)
      property int sm: style.space(4)
      property int md: style.space(6)
    }
    property QtObject font: QtObject {
      property string menuFamily: "monospace"
      property int body: root.baseFontSize
      property int caption: Math.round(root.baseFontSize * 0.833)
    }
  }

  component Button: Item {
    objectName: tooltipText
    property string iconText: ""
    property string tooltipText: ""
    property bool focusable: false
    property bool active: false
    property color foreground: "white"
    property color accent: "cyan"
    signal clicked()
    implicitWidth: icon.implicitWidth + style.space(10) * 2 + 2
    implicitHeight: icon.implicitHeight + style.space(6) * 2 + 2
    Text {
      id: icon
      text: "M"
      font.family: style.font.menuFamily
      font.pixelSize: Math.round(root.baseFontSize * 1.167)
    }
  }

  component PanelSlider: Item {
    objectName: "Volume slider"
    property real minimum: 0
    property real maximum: 100
    property real step: 1
    property bool integer: true
    property real value: 100
    property color trackColor: "gray"
    property color fillColor: "cyan"
    property color knobColor: "white"
    property color tickColor: "black"
    readonly property real knobSize: Math.max(14, Math.round(style.space(28) * 0.38))
    signal moved(real nextVolume)
    signal rightClicked()
    implicitWidth: style.space(200)
    implicitHeight: Math.max(style.space(22), knobSize + style.spacing.md)
  }

  ${panel.replaceAll("Style.", "style.")}

  function test_controlsFit_data() {
    return [
      { tag: "normal", panelWidth: 390, fontSize: 12 },
      { tag: "small-window", panelWidth: 312, fontSize: 12 },
      { tag: "small-window-larger-font", panelWidth: 442, fontSize: 17 },
      { tag: "small-window-large-font", panelWidth: 624, fontSize: 24 },
      { tag: "large-font-fixed-spacing", panelWidth: 312, fontSize: 24, spacingScaleWithFont: false }
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
    baseFontSize = data.fontSize
    spacingScaleWithFont = data.spacingScaleWithFont !== false
    waitForPolish(outputControls)
    var controls = controlsIn(playerPanel)
    compare(controls.length, 9, "Favorite, six playback/output buttons, slider, percentage")
    var status = playerPanel.children.find(function(item) {
      return item.text && item.text.indexOf(root.playingTrackTitle) === 0
    })
    verify(status !== undefined, "Track metadata must be present")
    var statusBottom = bounds(status).bottom
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i]
      var label = control.objectName || control.text
      var rect = bounds(control)
      verify(rect.left >= 0 && rect.right <= playerPanel.width + 0.5,
        label + " must fit horizontally")
      verify(rect.top >= 0 && rect.bottom <= playerPanel.height + 0.5,
        label + " must fit vertically")
      if (control !== playingFavoriteButton)
        verify(rect.top >= statusBottom + style.spacing.md - 0.5,
          label + " must stay below station metadata")
      for (var j = 0; j < i; j++) {
        var other = bounds(controls[j])
        verify(rect.right <= other.left + 0.5 || rect.left >= other.right - 0.5
          || rect.bottom <= other.top + 0.5 || rect.top >= other.bottom - 0.5,
          label + " overlaps " + (controls[j].objectName || controls[j].text))
      }
      if (control.text === "100%")
        verify(control.width >= control.implicitWidth - 0.5, "The percentage must not clip")
    }
    verify(volumeSlider.width >= volumeSlider.knobSize * 2, "Keep a usable volume track")
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner", ["-platform", "offscreen", "-input", directory], {
    env: { ...process.env, QT_QUICK_BACKEND: "software" },
    stdio: "inherit",
  })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Player layout tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
