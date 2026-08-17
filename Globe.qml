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
  property real maximumScale: 24
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
  property var preparedCountries: []
  property var preparedGrid: []
  property var preparedStations: []

  signal stationActivated(var station)
  signal countryActivated(string code, string name)
  signal interactionStarted()
  signal pointerMoved()

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

    centreLatitude = RadioModel.clamp(nextLatitude, -78, 78)
    centreLongitude = RadioModel.wrapLongitude(nextLongitude)
  }

  function focusCountry(code) {
    var coordinate = RadioModel.countryCentre(countries, code)
    if (coordinate) focusCoordinate(coordinate.latitude, coordinate.longitude)
  }

  function prepareCoordinates(coordinates, latitudeFirst) {
    var output = []
    if (!Array.isArray(coordinates)) return output
    for (var i = 0; i < coordinates.length; i++) {
      var latitude = Number(coordinates[i][latitudeFirst ? 0 : 1]) * Math.PI / 180
      var longitude = Number(coordinates[i][latitudeFirst ? 1 : 0]) * Math.PI / 180
      if (!isFinite(latitude) || !isFinite(longitude)) continue
      var cosLatitude = Math.cos(latitude)
      output.push(
        cosLatitude * Math.cos(longitude),
        cosLatitude * Math.sin(longitude),
        Math.sin(latitude))
    }
    return output
  }

  function prepareCountryGeometry() {
    var output = []
    var rows = Array.isArray(countries) ? countries : []
    for (var i = 0; i < rows.length; i++) {
      var feature = rows[i]
      if (!feature || !feature.geometry) continue
      var geometry = feature.geometry
      var polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates
      if (!Array.isArray(polygons)) continue
      var rings = []
      for (var p = 0; p < polygons.length; p++) {
        var ring = polygons[p] && polygons[p][0]
        var prepared = prepareCoordinates(ring, false)
        if (prepared.length >= 9) rings.push({ world: prepared, projected: new Array(prepared.length) })
      }
      if (rings.length === 0) continue
      output.push({
        code: String(feature.properties && feature.properties.code || "").toUpperCase(),
        rings: rings
      })
    }
    return output
  }

  function prepareGridGeometry() {
    var output = []
    for (var latitude = -60; latitude <= 60; latitude += 30) {
      var parallel = []
      for (var longitude = -180; longitude <= 180; longitude += 3)
        parallel.push([latitude, longitude])
      output.push(prepareCoordinates(parallel, true))
    }
    for (var meridian = -150; meridian <= 180; meridian += 30) {
      var line = []
      for (var lat = -90; lat <= 90; lat += 3) line.push([lat, meridian])
      output.push(prepareCoordinates(line, true))
    }
    return output
  }

  function prepareStationGeometry() {
    var output = []
    var rows = Array.isArray(stations) ? stations : []
    for (var i = 0; i < rows.length; i++) {
      var station = rows[i]
      if (!station || station.latitude === null || station.longitude === null) continue
      var latitude = Number(station.latitude) * Math.PI / 180
      var longitude = Number(station.longitude) * Math.PI / 180
      if (!isFinite(latitude) || !isFinite(longitude)) continue
      var cosLatitude = Math.cos(latitude)
      output.push({
        station: station,
        worldX: cosLatitude * Math.cos(longitude),
        worldY: cosLatitude * Math.sin(longitude),
        worldZ: Math.sin(latitude),
        visible: false,
        screenX: 0,
        screenY: 0,
        depth: -1
      })
    }
    return output
  }

  function paintCurve(ctx, coordinates, centreX, centreY, globeRadius,
                      sinLatitude, cosLatitude, sinLongitude, cosLongitude) {
    var drawing = false
    ctx.beginPath()
    for (var i = 0; i < coordinates.length; i += 3) {
      var horizontal = coordinates[i] * cosLongitude + coordinates[i + 1] * sinLongitude
      var xProjection = coordinates[i + 1] * cosLongitude - coordinates[i] * sinLongitude
      var yProjection = cosLatitude * coordinates[i + 2] - sinLatitude * horizontal
      var depth = sinLatitude * coordinates[i + 2] + cosLatitude * horizontal
      if (depth < 0) {
        drawing = false
        continue
      }
      var x = centreX + xProjection * globeRadius
      var y = centreY - yProjection * globeRadius
      if (!drawing) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
      drawing = true
    }
    ctx.stroke()
  }

  function paintGrid(ctx, centreX, centreY, globeRadius) {
    ctx.strokeStyle = withAlpha(gridColor, 0.18)
    ctx.lineWidth = Math.min(1.5, Math.max(0.7, globeRadius / 500))
    var latitude = centreLatitude * Math.PI / 180
    var longitude = centreLongitude * Math.PI / 180
    var sinLatitude = Math.sin(latitude)
    var cosLatitude = Math.cos(latitude)
    var sinLongitude = Math.sin(longitude)
    var cosLongitude = Math.cos(longitude)
    for (var i = 0; i < preparedGrid.length; i++)
      paintCurve(ctx, preparedGrid[i], centreX, centreY, globeRadius,
        sinLatitude, cosLatitude, sinLongitude, cosLongitude)
  }

  function paintCountries(ctx, centreX, centreY, globeRadius) {
    var rows = preparedCountries
    var latitude = centreLatitude * Math.PI / 180
    var longitude = centreLongitude * Math.PI / 180
    var sinLatitude = Math.sin(latitude)
    var cosLatitude = Math.cos(latitude)
    var sinLongitude = Math.sin(longitude)
    var cosLongitude = Math.cos(longitude)
    var activeCode = activeCountryCode.toUpperCase()
    for (var i = 0; i < rows.length; i++) {
      var country = rows[i]
      var active = country.code === activeCode
      ctx.fillStyle = active ? withAlpha(accentColor, 0.38) : withAlpha(landColor, 0.9)
      ctx.strokeStyle = active ? withAlpha(accentColor, 0.95) : withAlpha(outlineColor, 0.34)
      ctx.lineWidth = active ? 1.5 : 0.7

      for (var ringIndex = 0; ringIndex < country.rings.length; ringIndex++) {
        var geometry = country.rings[ringIndex]
        var ring = geometry.world
        var projected = geometry.projected
        var points = Math.floor(ring.length / 3)
        var hiddenIndex = -1
        for (var pointIndex = 0; pointIndex < points; pointIndex++) {
          var hiddenOffset = pointIndex * 3
          var hiddenHorizontal = ring[hiddenOffset] * cosLongitude
            + ring[hiddenOffset + 1] * sinLongitude
          projected[hiddenOffset] = ring[hiddenOffset + 1] * cosLongitude
            - ring[hiddenOffset] * sinLongitude
          projected[hiddenOffset + 1] = cosLatitude * ring[hiddenOffset + 2]
            - sinLatitude * hiddenHorizontal
          projected[hiddenOffset + 2] = sinLatitude * ring[hiddenOffset + 2]
            + cosLatitude * hiddenHorizontal
          if (projected[hiddenOffset + 2] < 0 && hiddenIndex < 0) {
            hiddenIndex = pointIndex
          }
        }

        if (hiddenIndex < 0) {
          ctx.beginPath()
          for (var visibleIndex = 0; visibleIndex < points; visibleIndex++) {
            var visibleOffset = visibleIndex * 3
            var visibleX = projected[visibleOffset]
            var visibleY = projected[visibleOffset + 1]
            var screenX = centreX + visibleX * globeRadius
            var screenY = centreY - visibleY * globeRadius
            if (visibleIndex === 0) ctx.moveTo(screenX, screenY)
            else ctx.lineTo(screenX, screenY)
          }
          ctx.closePath()
          ctx.fill()
          ctx.stroke()
          continue
        }

        var previousOffset = hiddenIndex * 3
        var previousX = projected[previousOffset]
        var previousY = projected[previousOffset + 1]
        var previousDepth = projected[previousOffset + 2]
        var drawing = false
        var startAngle = 0

        for (var step = 1; step <= points; step++) {
          var currentIndex = (hiddenIndex + step) % points
          var currentOffset = currentIndex * 3
          var currentX = projected[currentOffset]
          var currentY = projected[currentOffset + 1]
          var currentDepth = projected[currentOffset + 2]
          var previousVisible = previousDepth >= 0
          var currentVisible = currentDepth >= 0

          if (!previousVisible && currentVisible) {
            var enteringRatio = previousDepth / (previousDepth - currentDepth)
            var enteringX = previousX + (currentX - previousX) * enteringRatio
            var enteringY = previousY + (currentY - previousY) * enteringRatio
            var enteringLength = Math.sqrt(enteringX * enteringX + enteringY * enteringY) || 1
            enteringX /= enteringLength
            enteringY /= enteringLength
            startAngle = Math.atan2(-enteringY, enteringX)
            ctx.beginPath()
            ctx.moveTo(centreX + enteringX * globeRadius, centreY - enteringY * globeRadius)
            ctx.lineTo(centreX + currentX * globeRadius, centreY - currentY * globeRadius)
            drawing = true
          } else if (previousVisible && currentVisible && drawing) {
            ctx.lineTo(centreX + currentX * globeRadius, centreY - currentY * globeRadius)
          } else if (previousVisible && !currentVisible && drawing) {
            var leavingRatio = previousDepth / (previousDepth - currentDepth)
            var leavingX = previousX + (currentX - previousX) * leavingRatio
            var leavingY = previousY + (currentY - previousY) * leavingRatio
            var leavingLength = Math.sqrt(leavingX * leavingX + leavingY * leavingY) || 1
            leavingX /= leavingLength
            leavingY /= leavingLength
            var endAngle = Math.atan2(-leavingY, leavingX)
            var clockwiseArc = (startAngle - endAngle + Math.PI * 2) % (Math.PI * 2)
            ctx.lineTo(centreX + leavingX * globeRadius, centreY - leavingY * globeRadius)
            ctx.stroke()
            ctx.arc(centreX, centreY, globeRadius, endAngle, startAngle, clockwiseArc > Math.PI)
            ctx.closePath()
            ctx.fill()
            drawing = false
          }

          previousX = currentX
          previousY = currentY
          previousDepth = currentDepth
        }
      }
    }
  }

  function paintSignals(ctx) {
    var rows = preparedStations
    var latitude = centreLatitude * Math.PI / 180
    var longitude = centreLongitude * Math.PI / 180
    var sinLatitude = Math.sin(latitude)
    var cosLatitude = Math.cos(latitude)
    var sinLongitude = Math.sin(longitude)
    var cosLongitude = Math.cos(longitude)
    var globeRadius = radius()
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i]
      var horizontal = row.worldX * cosLongitude + row.worldY * sinLongitude
      var xProjection = row.worldY * cosLongitude - row.worldX * sinLongitude
      var yProjection = cosLatitude * row.worldZ - sinLatitude * horizontal
      var depth = sinLatitude * row.worldZ + cosLatitude * horizontal
      row.visible = depth >= 0
      if (!row.visible) continue
      row.screenX = globeCanvas.width / 2 + xProjection * globeRadius
      row.screenY = globeCanvas.height / 2 - yProjection * globeRadius
      row.depth = depth

      var selected = selectedStation && row.station.uuid === selectedStation.uuid
      var markerRadius = selected ? 4.2 : 1.7 + depth * 1.25
      ctx.beginPath()
      ctx.arc(row.screenX, row.screenY, markerRadius, 0, Math.PI * 2)
      ctx.fillStyle = selected ? accentColor : withAlpha(signalColor, 0.42 + depth * 0.48)
      ctx.fill()

      if (selected) {
        ctx.beginPath()
        ctx.arc(row.screenX, row.screenY, 8.5, 0, Math.PI * 2)
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
    if (!isFinite(globeRadius) || globeRadius <= 0) return

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
    var nearest = null
    var nearestDistance = 144
    for (var i = 0; i < preparedStations.length; i++) {
      var row = preparedStations[i]
      if (!row.visible) continue
      var deltaX = row.screenX - x
      var deltaY = row.screenY - y
      var distance = deltaX * deltaX + deltaY * deltaY
      if (distance > nearestDistance) continue
      nearest = row.station
      nearestDistance = distance
    }
    return nearest
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
    preparedCountries = prepareCountryGeometry()
    globeCanvas.requestPaint()
    if (activeCountryCode) focusCountry(activeCountryCode)
  }
  onStationsChanged: {
    preparedStations = prepareStationGeometry()
    globeCanvas.requestPaint()
  }
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

  Component.onCompleted: {
    preparedGrid = prepareGridGeometry()
    preparedCountries = prepareCountryGeometry()
    preparedStations = prepareStationGeometry()
    globeCanvas.requestPaint()
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
    property real totalMovement: 0

    onPressed: function(mouse) {
      root.interactionStarted()
      lastX = mouse.x
      lastY = mouse.y
      totalMovement = 0
      root.hoveredStation = null
    }

    onPositionChanged: function(mouse) {
      root.hoverX = mouse.x
      root.hoverY = mouse.y
      if (!(pressedButtons & Qt.LeftButton)) {
        root.pointerMoved()
        root.hoveredStation = root.stationUnderPointer(mouse.x, mouse.y)
        return
      }

      var deltaX = mouse.x - lastX
      var deltaY = mouse.y - lastY
      var longitudeDelta = -deltaX * root.longitudeSensitivity / root.globeScale
      var latitudeDelta = deltaY * root.latitudeSensitivity / root.globeScale

      root.centreLongitude = RadioModel.wrapLongitude(root.centreLongitude + longitudeDelta)
      root.centreLatitude = RadioModel.clamp(root.centreLatitude + latitudeDelta, -78, 78)
      totalMovement += Math.abs(deltaX) + Math.abs(deltaY)
      lastX = mouse.x
      lastY = mouse.y
    }

    onReleased: function(mouse) {
      if (totalMovement < 7) {
        root.activateAt(mouse.x, mouse.y)
        root.hoveredStation = root.stationUnderPointer(mouse.x, mouse.y)
      }
    }

    onExited: if (!(pressedButtons & Qt.LeftButton)) root.hoveredStation = null

    onWheel: function(wheel) {
      root.interactionStarted()
      var factor = Math.exp(wheel.angleDelta.y / 720)
      root.globeScale = RadioModel.clamp(
        root.globeScale * factor, root.minimumScale, root.maximumScale)
      wheel.accepted = true
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
      text: root.hoveredStation
        ? root.hoveredStation.name
          + (root.hoveredStation.estimatedLocation === true ? " · approximate location" : "")
        : ""
      textFormat: Text.PlainText
      color: root.textColor
      font.family: root.fontFamily
      font.pixelSize: 12
      elide: Text.ElideRight
    }
  }
}
