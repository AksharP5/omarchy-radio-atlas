import QtQuick 6.5
import QtTest
import "../.." as Atlas

TestCase {
  id: testCase
  name: "Globe"
  when: windowShown
  width: 800
  height: 600
  visible: true

  Atlas.Globe {
    id: globe
    width: 800
    height: 600
  }

  SignalSpy {
    id: selectionChanges
    target: globe
    signalName: "selectedStationUuidChanged"
  }

  SignalSpy {
    id: activations
    target: globe
    signalName: "stationActivated"
  }

  Component {
    id: countedGlobe
    Atlas.Globe {
      width: 800
      height: 600
      property var colorConversions: ({ count: 0 })
      function withAlpha(color, alpha) {
        colorConversions.count += 1
        return Qt.rgba(color.r, color.g, color.b, alpha)
      }
    }
  }

  Canvas {
    id: markerCanvas
    width: 800
    height: 600
    visible: false
    property bool reference: false
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      if (reference) testCase.paintReferenceMarkers(ctx)
      else globe.paintSignals(ctx)
    }
  }

  function init() {
    globe.stopKineticRotation(true)
    markerCanvas.visible = false
    globe.centreLatitude = 0
    globe.centreLongitude = 0
    globe.globeScale = 1
    globe.stations = []
    globe.selectedStation = null
    globe.highlightedStation = null
    globe.signalColor = "#d9dee3"
    globe.accentColor = "#ff8a3d"
    selectionChanges.clear()
    activations.clear()
  }

  function cleanup() {
    globe.stopKineticRotation(true)
  }

  function test_dragRotatesWithoutActivatingStation() {
    globe.stations = [{ uuid: "centre", latitude: 0, longitude: 0 }]
    waitForRendering(globe)
    mouseMove(globe, 400, 300, 20)
    mouseDrag(globe, 400, 300, 75, 20, Qt.LeftButton, Qt.NoModifier, 20)
    verify(globe.centreLongitude < 0)
    verify(globe.centreLatitude > 0)
    compare(activations.count, 0)
  }

  function test_kineticRotationMovesAndHighlightsLanding() {
    globe.stations = [{ uuid: "landing", latitude: 0, longitude: 0 }]
    waitForRendering(globe)
    verify(globe.startKineticRotation(150, 0))
    tryVerify(function() {
      if (globe.highlightedStation) return true
      // A stalled frame cancels motion without a landing. Retry that launch.
      if (globe.kineticVelocityX === 0) globe.startKineticRotation(150, 0)
      return false
    })
    verify(globe.centreLongitude < 0)
    compare(globe.centreLatitude, 0)
    compare(globe.kineticVelocityX, 0)
    compare(globe.kineticVelocityY, 0)
    compare(globe.highlightedStation.uuid, "landing")
    compare(activations.count, 0)
  }

  function test_statusUpdatePreservesLandingHighlight() {
    globe.selectedStation = { uuid: "playing", name: "Radio", latitude: 0, longitude: 0 }
    globe.highlightedStation = { uuid: "landing", latitude: 0, longitude: 5 }
    selectionChanges.clear()

    globe.selectedStation = { uuid: "playing", name: "Updated metadata", latitude: 0, longitude: 0 }
    compare(selectionChanges.count, 0)
    compare(globe.highlightedStation.uuid, "landing")

    globe.selectedStation = { uuid: "different", latitude: 0, longitude: 10 }
    compare(selectionChanges.count, 1)
    compare(globe.highlightedStation, null)
  }

  function test_themeChangeRepaintsWithoutInteraction() {
    globe.backgroundColor = "#000000"
    tryVerify(function() { return Qt.colorEqual(grabImage(globe).pixel(2, 2), "#000000") })
    globe.backgroundColor = "#ffffff"
    tryVerify(function() { return Qt.colorEqual(grabImage(globe).pixel(2, 2), "#ffffff") })
  }

  function test_offscreenMarkersAreSkippedButEdgeMarkersRemainClickable() {
    globe.globeScale = 3
    var edgeLongitude = Math.asin((-6 - globe.width / 2) / globe.radius()) * 180 / Math.PI
    var edge = { uuid: "edge", latitude: 0, longitude: edgeLongitude }
    globe.stations = [
      { uuid: "centre", latitude: 0, longitude: 0 },
      { uuid: "offscreen", latitude: 0, longitude: 60 },
      { uuid: "back", latitude: 0, longitude: 180 },
      edge
    ]
    globe.selectedStation = edge
    var arcs = []
    var context = {
      beginPath: function() {},
      arc: function(x, y, radius) { arcs.push({ x: x, y: y, radius: radius }) },
      fill: function() {},
      stroke: function() {}
    }
    globe.paintSignals(context)
    compare(arcs.length, 3)
    compare(arcs[2].radius, 8.5)
    compare(globe.stationUnderPointer(0, globe.height / 2).uuid, "edge")
    compare(globe.stationUnderPointer(globe.width / 2, globe.height / 2).uuid, "centre")

    globe.centreLongitude = 180
    globe.paintSignals(context)
    compare(globe.stationUnderPointer(globe.width / 2, globe.height / 2).uuid, "back")
  }

  function test_markerColorsAreConvertedOncePerPaint() {
    var item = createTemporaryObject(countedGlobe, testCase)
    verify(item)
    var rows = []
    for (var i = 0; i < 5000; i++)
      rows.push({ uuid: "station-" + i, latitude: 0, longitude: 0 })
    item.stations = rows
    item.selectedStation = rows[1]
    item.highlightedStation = rows[3]
    item.colorConversions.count = 0
    var fills = 0
    var context = {
      beginPath: function() {},
      arc: function() {},
      fill: function() { fills += 1 },
      stroke: function() {}
    }
    item.paintSignals(context)
    compare(fills, 5000)
    compare(item.colorConversions.count, 3)
    compare(context.globalAlpha, 1)
  }

  // Keep the original per-marker brush-alpha path as a pixel reference.
  function paintReferenceMarkers(ctx) {
    for (var i = 0; i < globe.preparedStations.length; i++) {
      var row = globe.preparedStations[i]
      if (!row.visible) continue
      var selected = globe.selectedStation && row.station.uuid === globe.selectedStation.uuid
      var highlighted = globe.highlightedStation
        && row.station.uuid === globe.highlightedStation.uuid && !selected
      ctx.beginPath()
      ctx.arc(row.screenX, row.screenY,
        selected ? 4.2 : (highlighted ? 3.7 : 1.7 + row.depth * 1.25), 0, Math.PI * 2)
      ctx.fillStyle = selected || highlighted
        ? globe.accentColor : globe.withAlpha(globe.signalColor, 0.42 + row.depth * 0.48)
      ctx.fill()
      if (selected || highlighted) {
        ctx.beginPath()
        ctx.arc(row.screenX, row.screenY, selected ? 8.5 : 7.5, 0, Math.PI * 2)
        ctx.strokeStyle = globe.withAlpha(globe.accentColor, selected ? 0.72 : 0.92)
        ctx.lineWidth = selected ? 1.2 : 1.4
        ctx.stroke()
      }
    }
  }

  function test_markerOpacityMatchesReference_data() {
    return [
      { tag: "opaque", signal: "#d9dee3", accent: "#ff8a3d" },
      { tag: "translucent", signal: "#40d9dee3", accent: "#80ff8a3d" }
    ]
  }

  function test_markerOpacityMatchesReference(data) {
    // Ordinary markers surround both active styles, including overlaps.
    globe.stations = [
      { uuid: "ordinary", latitude: 0, longitude: -10 },
      { uuid: "selected", latitude: 0, longitude: -5 },
      { uuid: "overlap", latitude: 0, longitude: -5 },
      { uuid: "highlighted", latitude: 0, longitude: 5 },
      { uuid: "last", latitude: 0, longitude: 5.4 }
    ]
    globe.selectedStation = globe.stations[1]
    globe.highlightedStation = globe.stations[3]
    globe.signalColor = data.signal
    globe.accentColor = data.accent
    markerCanvas.reference = false
    markerCanvas.visible = true
    markerCanvas.requestPaint()
    waitForRendering(markerCanvas)
    var actual = grabImage(markerCanvas)
    markerCanvas.reference = true
    markerCanvas.requestPaint()
    waitForRendering(markerCanvas)
    var expected = grabImage(markerCanvas)
    verify(actual.alpha(377, 300) > 0)
    for (var y = 288; y <= 312; y++) {
      for (var x = 345; x <= 438; x++) {
        // Compare premultiplied colors: nearly transparent antialiased pixels
        // amplify rounding when converted back to straight RGB.
        var actualAlpha = actual.alpha(x, y) / 255
        var expectedAlpha = expected.alpha(x, y) / 255
        verify(Math.abs(actual.alpha(x, y) - expected.alpha(x, y)) <= 3)
        verify(Math.abs(actual.red(x, y) * actualAlpha
          - expected.red(x, y) * expectedAlpha) <= 3)
        verify(Math.abs(actual.green(x, y) * actualAlpha
          - expected.green(x, y) * expectedAlpha) <= 3)
        verify(Math.abs(actual.blue(x, y) * actualAlpha
          - expected.blue(x, y) * expectedAlpha) <= 3)
      }
    }
  }
}
