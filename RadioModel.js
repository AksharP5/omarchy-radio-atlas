var radians = Math.PI / 180
var degrees = 180 / Math.PI

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value))
}

function wrapLongitude(value) {
  var wrapped = (value + 180) % 360
  if (wrapped < 0) wrapped += 360
  return wrapped - 180
}

function project(latitude, longitude, centreLatitude, centreLongitude) {
  var phi = Number(latitude) * radians
  var lambda = wrapLongitude(Number(longitude) - Number(centreLongitude)) * radians
  var phi0 = Number(centreLatitude) * radians
  var cosPhi = Math.cos(phi)
  var sinPhi = Math.sin(phi)
  var cosPhi0 = Math.cos(phi0)
  var sinPhi0 = Math.sin(phi0)

  return {
    x: cosPhi * Math.sin(lambda),
    y: cosPhi0 * sinPhi - sinPhi0 * cosPhi * Math.cos(lambda),
    z: sinPhi0 * sinPhi + cosPhi0 * cosPhi * Math.cos(lambda)
  }
}

function unproject(x, y, centreLatitude, centreLongitude) {
  var rho2 = x * x + y * y
  if (rho2 > 1) return null

  var z = Math.sqrt(Math.max(0, 1 - rho2))
  var phi0 = Number(centreLatitude) * radians
  var cosPhi0 = Math.cos(phi0)
  var sinPhi0 = Math.sin(phi0)
  var latitude = Math.asin(y * cosPhi0 + z * sinPhi0)
  var longitude = Number(centreLongitude) * radians
    + Math.atan2(x, z * cosPhi0 - y * sinPhi0)

  return {
    latitude: latitude * degrees,
    longitude: wrapLongitude(longitude * degrees)
  }
}

function pointInRing(longitude, latitude, ring) {
  var inside = false
  if (!Array.isArray(ring) || ring.length < 3) return false

  for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    var xi = Number(ring[i][0])
    var yi = Number(ring[i][1])
    var xj = Number(ring[j][0])
    var yj = Number(ring[j][1])
    var crosses = (yi > latitude) !== (yj > latitude)
      && longitude < (xj - xi) * (latitude - yi) / ((yj - yi) || 1e-12) + xi
    if (crosses) inside = !inside
  }
  return inside
}

function pointInPolygon(longitude, latitude, polygon) {
  if (!Array.isArray(polygon) || polygon.length === 0) return false
  if (!pointInRing(longitude, latitude, polygon[0])) return false

  for (var i = 1; i < polygon.length; i++) {
    if (pointInRing(longitude, latitude, polygon[i])) return false
  }
  return true
}

function countryAt(features, latitude, longitude) {
  var rows = Array.isArray(features) ? features : []
  for (var i = 0; i < rows.length; i++) {
    var feature = rows[i]
    if (!feature || !feature.geometry) continue
    var geometry = feature.geometry
    var polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates
    if (!Array.isArray(polygons)) continue

    for (var p = 0; p < polygons.length; p++) {
      if (pointInPolygon(longitude, latitude, polygons[p])) return feature.properties || null
    }
  }
  return null
}

function stationPosition(station, width, height, scale, centreLatitude, centreLongitude) {
  if (!station || station.latitude === null || station.longitude === null) return null
  var point = project(station.latitude, station.longitude, centreLatitude, centreLongitude)
  if (point.z < 0) return null
  var radius = Math.min(width, height) * 0.44 * scale
  return {
    x: width / 2 + point.x * radius,
    y: height / 2 - point.y * radius,
    z: point.z
  }
}

function stationAt(stations, x, y, width, height, scale, centreLatitude, centreLongitude, hitRadius) {
  var rows = Array.isArray(stations) ? stations : []
  var nearest = null
  var nearestDistance = Number(hitRadius || 12)

  for (var i = 0; i < rows.length; i++) {
    var position = stationPosition(rows[i], width, height, scale, centreLatitude, centreLongitude)
    if (!position) continue
    var dx = position.x - x
    var dy = position.y - y
    var distance = Math.sqrt(dx * dx + dy * dy)
    if (distance > nearestDistance) continue
    nearest = rows[i]
    nearestDistance = distance
  }
  return nearest
}

function mergeGeoStations(primary, secondary) {
  var output = []
  var seen = ({})
  var groups = [secondary, primary]

  for (var g = 0; g < groups.length; g++) {
    var rows = Array.isArray(groups[g]) ? groups[g] : []
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i]
      if (!row || !row.uuid || seen[row.uuid]) continue
      if (row.latitude === null || row.longitude === null) continue
      seen[row.uuid] = true
      output.push(row)
    }
  }
  return output.slice(0, 700)
}

function compactTags(tags, maximum) {
  var raw = String(tags || "")
  var parts = raw.split(",")
  var output = []
  var limit = Math.max(1, Number(maximum || 2))
  for (var i = 0; i < parts.length && output.length < limit; i++) {
    var part = parts[i].trim()
    if (part && output.indexOf(part) === -1) output.push(part)
  }
  return output.join(" · ")
}

function stationMeta(station) {
  if (!station) return ""
  var parts = []
  if (station.countryCode) parts.push(station.countryCode)
  if (station.codec) parts.push(station.codec)
  if (Number(station.bitrate) > 0) parts.push(Number(station.bitrate) + " kbps")
  return parts.join(" · ")
}

function indexByUuid(stations, uuid) {
  var rows = Array.isArray(stations) ? stations : []
  for (var i = 0; i < rows.length; i++) if (rows[i].uuid === uuid) return i
  return -1
}
