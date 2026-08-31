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
  property bool kineticRotationEnabled: true

  readonly property real kineticLaunchSpeed: 120
  readonly property real kineticMaximumSpeed: 2400
  readonly property real kineticDeceleration: 1800
  readonly property real kineticMaximumFrameTime: 0.1
  readonly property real kineticMaximumSampleAge: 100

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
  property var highlightedStation: null
  property real highlightX: 0
  property real highlightY: 0
  property real kineticVelocityX: 0
  property real kineticVelocityY: 0
  property int kineticLaunchGeneration: 0
  property bool suppressNextTap: false
  property var preparedCountries: []
  property var preparedGrid: []
  property var preparedStations: []

  signal stationActivated(var station)
  signal countryActivated(string code, string name)
  signal interactionStarted()
  signal pointerMoved()

  Accessible.name: "Interactive world radio globe"
  Accessible.description: "Drag or flick to rotate, use the mouse wheel to zoom, and select a station signal or country"
  Accessible.role: Accessible.Pane

  function radius() {
    return Math.min(width, height) * 0.44 * globeScale
  }

  function withAlpha(color, alpha) {
    return Qt.rgba(color.r, color.g, color.b, alpha)
  }

  function clearLandingHighlight() {
    highlightedStation = null
    highlightX = 0
    highlightY = 0
  }

  function stopKineticRotation(clearLanding) {
    kineticLaunchGeneration += 1
    kineticAnimation.running = false
    kineticVelocityX = 0
    kineticVelocityY = 0
    if (clearLanding === true) clearLandingHighlight()
  }

  function startKineticRotation(velocityX, velocityY) {
    if (!kineticRotationEnabled) return false
    var launch = RadioModel.kineticLaunchVelocity(
      velocityX, velocityY, kineticLaunchSpeed, kineticMaximumSpeed)
    if (!launch.active) return false

    kineticLaunchGeneration += 1
    clearLandingHighlight()
    hoveredStation = null
    kineticVelocityX = launch.x
    kineticVelocityY = launch.y
    kineticAnimation.running = true
    return true
  }

  function finishKineticRotation() {
    kineticAnimation.running = false
    kineticVelocityX = 0
    kineticVelocityY = 0
    hoveredStation = null
    var excludedUuid = selectedStation ? selectedStation.uuid : ""
    highlightedStation = RadioModel.nearestVisibleStation(
      stations, centreLatitude, centreLongitude, excludedUuid,
      width, height, globeScale)
  }

  function rotateByPointerDelta(deltaX, deltaY) {
    centreLongitude = RadioModel.wrapLongitude(
      centreLongitude - deltaX * longitudeSensitivity / globeScale)
    centreLatitude = RadioModel.clamp(
      centreLatitude + deltaY * latitudeSensitivity / globeScale, -78, 78)
  }

  function stationByUuid(uuid) {
    var wanted = String(uuid || "")
    var rows = Array.isArray(stations) ? stations : []
    for (var i = 0; i < rows.length; i++)
      if (String(rows[i] && rows[i].uuid || "") === wanted) return rows[i]
    return null
  }

  function refreshLandingHighlight() {
    if (!highlightedStation) return
    var replacement = stationByUuid(highlightedStation.uuid)
    if (!replacement) {
      clearLandingHighlight()
      return
    }
    highlightedStation = replacement
    updateHighlightPosition()
  }

  function updateHighlightPosition() {
    if (!highlightedStation) return
    var position = RadioModel.stationPosition(
      highlightedStation, width, height, globeScale, centreLatitude, centreLongitude)
    if (!position) {
      clearLandingHighlight()
      return
    }
    highlightX = position.x
    highlightY = position.y
  }

  function focusCoordinate(latitude, longitude) {
    var nextLatitude = Number(latitude)
    var nextLongitude = Number(longitude)
    if (!isFinite(nextLatitude) || !isFinite(nextLongitude)) return

    stopKineticRotation(true)
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
      var highlighted = highlightedStation
        && row.station.uuid === highlightedStation.uuid && !selected
      var markerRadius = selected ? 4.2 : (highlighted ? 3.7 : 1.7 + depth * 1.25)
      ctx.beginPath()
      ctx.arc(row.screenX, row.screenY, markerRadius, 0, Math.PI * 2)
      ctx.fillStyle = selected || highlighted
        ? accentColor : withAlpha(signalColor, 0.42 + depth * 0.48)
      ctx.fill()

      if (selected || highlighted) {
        ctx.beginPath()
        ctx.arc(row.screenX, row.screenY, selected ? 8.5 : 7.5, 0, Math.PI * 2)
        ctx.strokeStyle = withAlpha(accentColor, selected ? 0.72 : 0.92)
        ctx.lineWidth = selected ? 1.2 : 1.4
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
    clearLandingHighlight()
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
    refreshLandingHighlight()
    globeCanvas.requestPaint()
  }
  onSelectedStationChanged: {
    clearLandingHighlight()
    globeCanvas.requestPaint()
  }
  onActiveCountryCodeChanged: globeCanvas.requestPaint()
  onCentreLatitudeChanged: {
    updateHighlightPosition()
    globeCanvas.requestPaint()
  }
  onCentreLongitudeChanged: {
    updateHighlightPosition()
    globeCanvas.requestPaint()
  }
  onGlobeScaleChanged: {
    updateHighlightPosition()
    globeCanvas.requestPaint()
  }
  onWidthChanged: {
    updateHighlightPosition()
    globeCanvas.requestPaint()
  }
  onHeightChanged: {
    updateHighlightPosition()
    globeCanvas.requestPaint()
  }
  onHighlightedStationChanged: {
    updateHighlightPosition()
    globeCanvas.requestPaint()
  }
  onKineticRotationEnabledChanged: {
    if (!kineticRotationEnabled) stopKineticRotation(true)
  }
  onVisibleChanged: {
    if (!visible) stopKineticRotation(true)
  }

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

  HoverHandler {
    id: hoverHandler
    cursorShape: dragHandler.active || tapHandler.pressed
      ? Qt.ClosedHandCursor
      : (root.hoveredStation ? Qt.PointingHandCursor : Qt.OpenHandCursor)

    onPointChanged: {
      root.hoverX = point.position.x
      root.hoverY = point.position.y
      root.pointerMoved()
      root.hoveredStation = kineticAnimation.running || dragHandler.active
        ? null : root.stationUnderPointer(point.position.x, point.position.y)
    }

    onHoveredChanged: {
      if (!hovered) root.hoveredStation = null
    }
  }

  TapHandler {
    id: tapHandler
    acceptedButtons: Qt.LeftButton
    gesturePolicy: TapHandler.DragThreshold

    onPressedChanged: {
      if (!pressed) return
      root.interactionStarted()
      var caughtKineticRotation = kineticAnimation.running
      root.stopKineticRotation(true)
      root.suppressNextTap = caughtKineticRotation
      root.hoveredStation = null
    }

    onTapped: function(eventPoint) {
      if (root.suppressNextTap) {
        root.suppressNextTap = false
        return
      }
      root.activateAt(eventPoint.position.x, eventPoint.position.y)
      root.hoveredStation = hoverHandler.hovered
        ? root.stationUnderPointer(eventPoint.position.x, eventPoint.position.y) : null
    }

    onCanceled: root.suppressNextTap = false
  }

  DragHandler {
    id: dragHandler
    target: null
    acceptedButtons: Qt.LeftButton

    property bool wasActive: false
    property bool launchCanceled: false
    property bool launchPending: false
    property int pendingLaunchGeneration: 0
    property real pendingVelocityX: 0
    property real pendingVelocityY: 0
    property real recentVelocityX: 0
    property real recentVelocityY: 0
    property real recentVelocityAt: 0
    property real samplePositionX: 0
    property real samplePositionY: 0
    property real sampleStartedAt: 0

    function resetMotionSample() {
      recentVelocityX = 0
      recentVelocityY = 0
      recentVelocityAt = 0
      samplePositionX = centroid.position.x
      samplePositionY = centroid.position.y
      sampleStartedAt = Date.now()
    }

    function recordMotionSample() {
      // Qt's filtered mouse velocity can fall below the launch floor before
      // release. Keep a short, capped-by-launch recent sample for human-speed
      // flicks; the coast itself still uses frame-time-independent physics.
      var now = Date.now()
      var elapsedMilliseconds = now - sampleStartedAt
      if (elapsedMilliseconds <= 0) return

      var deltaX = centroid.position.x - samplePositionX
      var deltaY = centroid.position.y - samplePositionY
      samplePositionX = centroid.position.x
      samplePositionY = centroid.position.y
      sampleStartedAt = now
      if (elapsedMilliseconds > 250) return

      var sampledVelocityX = deltaX * 1000 / elapsedMilliseconds
      var sampledVelocityY = deltaY * 1000 / elapsedMilliseconds
      if (!isFinite(sampledVelocityX) || !isFinite(sampledVelocityY)) return
      if (recentVelocityAt > 0) {
        recentVelocityX = recentVelocityX * 0.25 + sampledVelocityX * 0.75
        recentVelocityY = recentVelocityY * 0.25 + sampledVelocityY * 0.75
      } else {
        recentVelocityX = sampledVelocityX
        recentVelocityY = sampledVelocityY
      }
      recentVelocityAt = now
    }

    onActiveChanged: {
      if (active) {
        root.stopKineticRotation(true)
        wasActive = true
        launchCanceled = false
        launchPending = false
        root.suppressNextTap = false
        root.interactionStarted()
        root.hoveredStation = null
        resetMotionSample()
        return
      }
      if (!wasActive) return

      wasActive = false
      var releaseVelocity = RadioModel.kineticReleaseVelocity(
        centroid.velocity.x, centroid.velocity.y,
        recentVelocityX, recentVelocityY,
        recentVelocityAt > 0 ? Date.now() - recentVelocityAt : Infinity,
        root.kineticMaximumSampleAge)
      pendingVelocityX = releaseVelocity.x
      pendingVelocityY = releaseVelocity.y
      pendingLaunchGeneration = root.kineticLaunchGeneration
      launchPending = !launchCanceled
      Qt.callLater(function() {
        if (!dragHandler.launchPending || dragHandler.launchCanceled) return
        if (dragHandler.pendingLaunchGeneration !== root.kineticLaunchGeneration) {
          dragHandler.launchPending = false
          return
        }
        dragHandler.launchPending = false
        root.startKineticRotation(
          dragHandler.pendingVelocityX, dragHandler.pendingVelocityY)
      })
    }

    onTranslationChanged: function(delta) {
      if (!active) return
      recordMotionSample()
      root.rotateByPointerDelta(delta.x, delta.y)
    }

    onCanceled: {
      launchCanceled = true
      launchPending = false
      recentVelocityAt = 0
      root.stopKineticRotation(false)
    }
  }

  WheelHandler {
    id: wheelHandler
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    blocking: true

    onWheel: function(event) {
      root.interactionStarted()
      root.stopKineticRotation(true)
      root.suppressNextTap = false
      root.hoveredStation = null
      var factor = Math.exp(event.angleDelta.y / 720)
      root.globeScale = RadioModel.clamp(
        root.globeScale * factor, root.minimumScale, root.maximumScale)
      event.accepted = true
    }
  }

  FrameAnimation {
    id: kineticAnimation
    running: false

    onTriggered: {
      if (!root.kineticRotationEnabled || frameTime > root.kineticMaximumFrameTime) {
        root.stopKineticRotation(true)
        return
      }
      if (frameTime <= 0) return

      var step = RadioModel.advanceKineticRotation({
        longitude: root.centreLongitude,
        latitude: root.centreLatitude,
        velocityX: root.kineticVelocityX,
        velocityY: root.kineticVelocityY
      }, frameTime, {
        deceleration: root.kineticDeceleration,
        scale: root.globeScale,
        longitudeSensitivity: root.longitudeSensitivity,
        latitudeSensitivity: root.latitudeSensitivity,
        minimumLatitude: -78,
        maximumLatitude: 78
      })
      root.kineticVelocityX = step.velocityX
      root.kineticVelocityY = step.velocityY
      root.centreLongitude = step.longitude
      root.centreLatitude = step.latitude
      if (!step.active) root.finishKineticRotation()
    }
  }

  Rectangle {
    id: tooltip
    property var station: root.hoveredStation || root.highlightedStation
    property bool landing: !root.hoveredStation && !!root.highlightedStation
    property real anchorX: root.hoveredStation ? root.hoverX : root.highlightX
    property real anchorY: root.hoveredStation ? root.hoverY : root.highlightY

    visible: !!station && !tapHandler.pressed && !dragHandler.active
      && !kineticAnimation.running
    x: Math.min(root.width - width - 8, Math.max(8, anchorX + 14))
    y: Math.min(root.height - height - 8, Math.max(8, anchorY + 14))
    width: landing
      ? Math.min(280, Math.max(0, root.width - 16))
      : Math.min(280, Math.max(0, root.width - 16), tooltipText.implicitWidth + 20)
    height: tooltipContent.implicitHeight + 14
    color: Qt.rgba(root.backgroundColor.r, root.backgroundColor.g, root.backgroundColor.b, 0.94)
    border.color: root.withAlpha(root.outlineColor, 0.5)
    border.width: 1
    radius: 2

    Column {
      id: tooltipContent
      anchors.centerIn: parent
      width: Math.max(0, parent.width - 20)
      spacing: 2

      Text {
        id: tooltipText
        width: parent.width
        text: tooltip.station
          ? (tooltip.landing ? "Landed near · " : "") + tooltip.station.name
            + (!tooltip.landing && tooltip.station.estimatedLocation === true
              ? " · approximate location" : "")
          : ""
        textFormat: Text.PlainText
        color: root.textColor
        font.family: root.fontFamily
        font.pixelSize: 12
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        visible: tooltip.landing && tooltip.station
          && tooltip.station.estimatedLocation === true
        text: "approximate location"
        textFormat: Text.PlainText
        color: root.withAlpha(root.textColor, 0.66)
        font.family: root.fontFamily
        font.pixelSize: 11
      }
    }
  }
}
