import QtQuick
import "RadioModel.js" as RadioModel

Item {
  id: root

  property var countries: []
  property var stations: []
  property var selectedStation: null
  property string activeCountryCode: ""

  property real centreLatitude: 18
  property real centreLongitude: -20
  property real globeScale: 1
  property real minimumScale: 0.72
  property real maximumScale: 1.28
  property real longitudeSensitivity: 0.22
  property real latitudeSensitivity: 0.18

  property color backgroundColor: "#090a0c"
  property color sphereColor: "#11151a"
  property color landColor: "#283039"
  property color gridColor: "#7d8791"
  property color outlineColor: "#9099a3"
  property color signalColor: "#d9dee3"
  property color accentColor: "#ff8a3d"
  property color textColor: "#f3f4f5"
  property string fontFamily: "monospace"

  property var hoveredStation: null
  property real hoverX: 0
  property real hoverY: 0
  property real inertiaLongitude: 0
  property real inertiaLatitude: 0
  property bool inertiaActive: false

  signal stationActivated(var station)
  signal countryActivated(string code, string name)
  signal interactionStarted()

  Accessible.name: "Interactive world radio globe"
  Accessible.description: "Drag to rotate, use the mouse wheel to zoom, and select a station signal or country"
  Accessible.role: Accessible.Pane

  function radius() {
    return Math.min(width, height) * 0.44 * globeScale
  }

  function withAlpha(color, alpha) {
    return Qt.rgba(color.r, color.g, color.b, alpha)
  }

  function focusCoordinate(latitude, longitude) {
    var nextLatitude = Number(latitude)
    var nextLongitude = Number(longitude)
    if (!isFinite(nextLatitude) || !isFinite(nextLongitude)) return

    inertiaActive = false
    centreLatitude = RadioModel.clamp(nextLatitude, -78, 78)
    centreLongitude = RadioModel.wrapLongitude(nextLongitude)
  }

  function focusCountry(code) {
    var coordinate = RadioModel.countryCentre(countries, code)
    if (coordinate) focusCoordinate(coordinate.latitude, coordinate.longitude)
  }

  function projectedSegments(ring) {
    var segments = []
    var segment = []
    if (!Array.isArray(ring)) return segments

    for (var i = 0; i < ring.length; i++) {
      var coordinate = ring[i]
      var point = RadioModel.project(coordinate[1], coordinate[0], centreLatitude, centreLongitude)
      if (point.z >= 0) {
        segment.push(point)
      } else if (segment.length > 0) {
        segments.push(segment)
        segment = []
      }
    }
    if (segment.length > 0) segments.push(segment)

    if (segments.length > 1 && ring.length > 1) {
      var first = RadioModel.project(ring[0][1], ring[0][0], centreLatitude, centreLongitude)
      var lastCoordinate = ring[ring.length - 1]
      var last = RadioModel.project(lastCoordinate[1], lastCoordinate[0], centreLatitude, centreLongitude)
      if (first.z >= 0 && last.z >= 0) {
        segments[0] = segments[segments.length - 1].concat(segments[0])
        segments.pop()
      }
    }
    return segments
  }

  function paintCurve(ctx, coordinates, centreX, centreY, globeRadius) {
    var drawing = false
    ctx.beginPath()
    for (var i = 0; i < coordinates.length; i++) {
      var coordinate = coordinates[i]
      var point = RadioModel.project(coordinate[0], coordinate[1], centreLatitude, centreLongitude)
      if (point.z < 0) {
        drawing = false
        continue
      }
      var x = centreX + point.x * globeRadius
      var y = centreY - point.y * globeRadius
      if (!drawing) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
      drawing = true
    }
    ctx.stroke()
  }

  function paintGrid(ctx, centreX, centreY, globeRadius) {
    ctx.strokeStyle = withAlpha(gridColor, 0.18)
    ctx.lineWidth = Math.max(0.7, globeRadius / 500)

    for (var latitude = -60; latitude <= 60; latitude += 30) {
      var parallel = []
      for (var longitude = -180; longitude <= 180; longitude += 3)
        parallel.push([latitude, longitude])
      paintCurve(ctx, parallel, centreX, centreY, globeRadius)
    }

    for (var meridian = -150; meridian <= 180; meridian += 30) {
      var line = []
      for (var lat = -90; lat <= 90; lat += 3) line.push([lat, meridian])
      paintCurve(ctx, line, centreX, centreY, globeRadius)
    }
  }

  function paintCountries(ctx, centreX, centreY, globeRadius) {
    var rows = Array.isArray(countries) ? countries : []
    for (var i = 0; i < rows.length; i++) {
      var feature = rows[i]
      if (!feature || !feature.geometry) continue
      var geometry = feature.geometry
      var polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates
      if (!Array.isArray(polygons)) continue
      var active = feature.properties
        && String(feature.properties.code || "").toUpperCase() === activeCountryCode.toUpperCase()

      for (var p = 0; p < polygons.length; p++) {
        var polygon = polygons[p]
        if (!Array.isArray(polygon) || polygon.length === 0) continue
        var segments = projectedSegments(polygon[0])

        for (var s = 0; s < segments.length; s++) {
          var segment = segments[s]
          if (segment.length < 3) continue
          ctx.beginPath()
          for (var n = 0; n < segment.length; n++) {
            var point = segment[n]
            var x = centreX + point.x * globeRadius
            var y = centreY - point.y * globeRadius
            if (n === 0) ctx.moveTo(x, y)
            else ctx.lineTo(x, y)
          }
          ctx.closePath()
          ctx.fillStyle = active ? withAlpha(accentColor, 0.38) : withAlpha(landColor, 0.9)
          ctx.fill()
          ctx.strokeStyle = active ? withAlpha(accentColor, 0.95) : withAlpha(outlineColor, 0.34)
          ctx.lineWidth = active ? 1.5 : 0.7
          ctx.stroke()
        }
      }
    }
  }

  function paintSignals(ctx) {
    var rows = Array.isArray(stations) ? stations : []
    for (var i = 0; i < rows.length; i++) {
      var station = rows[i]
      var position = RadioModel.stationPosition(
        station, globeCanvas.width, globeCanvas.height, globeScale,
        centreLatitude, centreLongitude)
      if (!position) continue

      var selected = selectedStation && station.uuid === selectedStation.uuid
      var markerRadius = selected ? 4.2 : 1.7 + position.z * 1.25
      ctx.beginPath()
      ctx.arc(position.x, position.y, markerRadius, 0, Math.PI * 2)
      ctx.fillStyle = selected ? accentColor : withAlpha(signalColor, 0.42 + position.z * 0.48)
      ctx.fill()

      if (selected) {
        ctx.beginPath()
        ctx.arc(position.x, position.y, 8.5, 0, Math.PI * 2)
        ctx.strokeStyle = withAlpha(accentColor, 0.72)
        ctx.lineWidth = 1.2
        ctx.stroke()
      }
    }
  }

  function paintGlobe(ctx) {
    var centreX = globeCanvas.width / 2
    var centreY = globeCanvas.height / 2
    var globeRadius = radius()

    ctx.reset()
    ctx.fillStyle = backgroundColor
    ctx.fillRect(0, 0, globeCanvas.width, globeCanvas.height)

    var sphere = ctx.createRadialGradient(
      centreX - globeRadius * 0.28, centreY - globeRadius * 0.32, globeRadius * 0.04,
      centreX, centreY, globeRadius)
    sphere.addColorStop(0, withAlpha(Qt.lighter(sphereColor, 1.7), 1))
    sphere.addColorStop(0.62, sphereColor)
    sphere.addColorStop(1, Qt.darker(sphereColor, 1.8))
    ctx.beginPath()
    ctx.arc(centreX, centreY, globeRadius, 0, Math.PI * 2)
    ctx.fillStyle = sphere
    ctx.fill()

    ctx.save()
    ctx.beginPath()
    ctx.arc(centreX, centreY, globeRadius - 0.5, 0, Math.PI * 2)
    ctx.clip()
    paintGrid(ctx, centreX, centreY, globeRadius)
    paintCountries(ctx, centreX, centreY, globeRadius)
    paintSignals(ctx)
    ctx.restore()

    ctx.beginPath()
    ctx.arc(centreX, centreY, globeRadius, 0, Math.PI * 2)
    ctx.strokeStyle = withAlpha(outlineColor, 0.52)
    ctx.lineWidth = 1.1
    ctx.stroke()
  }

  function stationUnderPointer(x, y) {
    return RadioModel.stationAt(
      stations, x, y, globeCanvas.width, globeCanvas.height, globeScale,
      centreLatitude, centreLongitude, 12)
  }

  function activateAt(x, y) {
    var station = stationUnderPointer(x, y)
    if (station) {
      stationActivated(station)
      return
    }

    var globeRadius = radius()
    var normalizedX = (x - width / 2) / globeRadius
    var normalizedY = -(y - height / 2) / globeRadius
    var coordinate = RadioModel.unproject(
      normalizedX, normalizedY, centreLatitude, centreLongitude)
    if (!coordinate) return
    var country = RadioModel.countryAt(
      countries, coordinate.latitude, coordinate.longitude)
    if (!country || !country.code || country.code === "-99") return
    countryActivated(String(country.code).toUpperCase(), String(country.name || country.code))
  }

  onCountriesChanged: {
    globeCanvas.requestPaint()
    if (activeCountryCode) focusCountry(activeCountryCode)
  }
  onStationsChanged: globeCanvas.requestPaint()
  onSelectedStationChanged: globeCanvas.requestPaint()
  onActiveCountryCodeChanged: globeCanvas.requestPaint()
  onCentreLatitudeChanged: globeCanvas.requestPaint()
  onCentreLongitudeChanged: globeCanvas.requestPaint()
  onGlobeScaleChanged: globeCanvas.requestPaint()
  onWidthChanged: globeCanvas.requestPaint()
  onHeightChanged: globeCanvas.requestPaint()

  Canvas {
    id: globeCanvas
    anchors.fill: parent
    renderStrategy: Canvas.Cooperative
    onPaint: {
      var ctx = getContext("2d")
      if (ctx) root.paintGlobe(ctx)
    }
  }

  MouseArea {
    id: pointer
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton
    cursorShape: pressed
      ? Qt.ClosedHandCursor
      : (root.hoveredStation ? Qt.PointingHandCursor : Qt.OpenHandCursor)

    property real lastX: 0
    property real lastY: 0
    property real lastTime: 0
    property real totalMovement: 0

    onPressed: function(mouse) {
      root.interactionStarted()
      root.inertiaActive = false
      lastX = mouse.x
      lastY = mouse.y
      lastTime = Date.now()
      totalMovement = 0
      root.hoveredStation = null
    }

    onPositionChanged: function(mouse) {
      root.hoverX = mouse.x
      root.hoverY = mouse.y
      if (!(pressedButtons & Qt.LeftButton)) {
        root.hoveredStation = root.stationUnderPointer(mouse.x, mouse.y)
        return
      }

      var now = Date.now()
      var elapsed = Math.max(1, now - lastTime)
      var deltaX = mouse.x - lastX
      var deltaY = mouse.y - lastY
      var longitudeDelta = -deltaX * root.longitudeSensitivity / root.globeScale
      var latitudeDelta = deltaY * root.latitudeSensitivity / root.globeScale

      root.centreLongitude = RadioModel.wrapLongitude(root.centreLongitude + longitudeDelta)
      root.centreLatitude = RadioModel.clamp(root.centreLatitude + latitudeDelta, -78, 78)
      root.inertiaLongitude = longitudeDelta / elapsed
      root.inertiaLatitude = latitudeDelta / elapsed
      totalMovement += Math.abs(deltaX) + Math.abs(deltaY)
      lastX = mouse.x
      lastY = mouse.y
      lastTime = now
    }

    onReleased: function(mouse) {
      if (totalMovement < 7) {
        root.activateAt(mouse.x, mouse.y)
        root.hoveredStation = root.stationUnderPointer(mouse.x, mouse.y)
        return
      }
      root.inertiaActive = Math.abs(root.inertiaLongitude) + Math.abs(root.inertiaLatitude) > 0.015
    }

    onExited: if (!(pressedButtons & Qt.LeftButton)) root.hoveredStation = null

    onWheel: function(wheel) {
      root.interactionStarted()
      root.inertiaActive = false
      var factor = Math.exp(wheel.angleDelta.y / 1200)
      root.globeScale = RadioModel.clamp(
        root.globeScale * factor, root.minimumScale, root.maximumScale)
      wheel.accepted = true
    }
  }

  Timer {
    interval: 16
    repeat: true
    running: root.inertiaActive
    onTriggered: {
      root.centreLongitude = RadioModel.wrapLongitude(
        root.centreLongitude + root.inertiaLongitude * interval)
      root.centreLatitude = RadioModel.clamp(
        root.centreLatitude + root.inertiaLatitude * interval, -78, 78)
      root.inertiaLongitude *= 0.93
      root.inertiaLatitude *= 0.91
      if (Math.abs(root.inertiaLongitude) + Math.abs(root.inertiaLatitude) < 0.0015)
        root.inertiaActive = false
    }
  }

  Rectangle {
    id: tooltip
    visible: !!root.hoveredStation && !pointer.pressed
    x: Math.min(root.width - width - 8, Math.max(8, root.hoverX + 14))
    y: Math.min(root.height - height - 8, Math.max(8, root.hoverY + 14))
    width: Math.min(240, tooltipText.implicitWidth + 20)
    height: tooltipText.implicitHeight + 14
    color: Qt.rgba(root.backgroundColor.r, root.backgroundColor.g, root.backgroundColor.b, 0.94)
    border.color: root.withAlpha(root.outlineColor, 0.5)
    border.width: 1
    radius: 2

    Text {
      id: tooltipText
      anchors.centerIn: parent
      width: Math.min(220, implicitWidth)
      text: root.hoveredStation ? root.hoveredStation.name : ""
      color: root.textColor
      font.family: root.fontFamily
      font.pixelSize: 12
      elide: Text.ElideRight
    }
  }
}
