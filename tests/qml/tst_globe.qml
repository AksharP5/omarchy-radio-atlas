import QtQuick
import QtTest
import "../.." as Atlas

TestCase {
  name: "Globe"
  when: windowShown
  width: 800
  height: 600

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

  function init() {
    globe.centreLatitude = 0
    globe.centreLongitude = 0
    globe.globeScale = 1
    globe.stations = []
    globe.selectedStation = null
    globe.highlightedStation = null
    selectionChanges.clear()
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
}
