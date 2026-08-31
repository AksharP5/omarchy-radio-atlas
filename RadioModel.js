var radians = Math.PI / 180
var degrees = 180 / Math.PI
var estimatedLocationCache = ({})

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value))
}

function wrapLongitude(value) {
  var wrapped = (value + 180) % 360
  if (wrapped < 0) wrapped += 360
  return wrapped - 180
}

function limitKineticVelocity(x, y, maximumSpeed) {
  var velocityX = Number(x)
  var velocityY = Number(y)
  var limit = Number(maximumSpeed)
  if (!isFinite(velocityX) || !isFinite(velocityY) || !isFinite(limit) || limit <= 0)
    return { x: 0, y: 0, speed: 0 }

  var speed = Math.sqrt(velocityX * velocityX + velocityY * velocityY)
  if (!isFinite(speed) || speed <= 0) return { x: 0, y: 0, speed: 0 }
  if (speed <= limit) return { x: velocityX, y: velocityY, speed: speed }

  var ratio = limit / speed
  return { x: velocityX * ratio, y: velocityY * ratio, speed: limit }
}

function kineticLaunchVelocity(x, y, minimumSpeed, maximumSpeed) {
  var limited = limitKineticVelocity(x, y, maximumSpeed)
  var threshold = Math.max(0, Number(minimumSpeed) || 0)
  return {
    x: limited.speed >= threshold ? limited.x : 0,
    y: limited.speed >= threshold ? limited.y : 0,
    speed: limited.speed,
    active: limited.speed >= threshold
  }
}

function kineticReleaseVelocity(nativeX, nativeY, sampledX, sampledY,
                                sampleAgeMilliseconds, maximumSampleAgeMilliseconds) {
  var nativeVelocityX = Number(nativeX)
  var nativeVelocityY = Number(nativeY)
  var sampledVelocityX = Number(sampledX)
  var sampledVelocityY = Number(sampledY)
  if (!isFinite(nativeVelocityX)) nativeVelocityX = 0
  if (!isFinite(nativeVelocityY)) nativeVelocityY = 0
  if (!isFinite(sampledVelocityX)) sampledVelocityX = 0
  if (!isFinite(sampledVelocityY)) sampledVelocityY = 0

  var nativeSpeed = Math.sqrt(
    nativeVelocityX * nativeVelocityX + nativeVelocityY * nativeVelocityY)
  var sampledSpeed = Math.sqrt(
    sampledVelocityX * sampledVelocityX + sampledVelocityY * sampledVelocityY)
  var sampleAge = Number(sampleAgeMilliseconds)
  var maximumSampleAge = Math.max(0, Number(maximumSampleAgeMilliseconds) || 0)
  var sampleIsFresh = isFinite(sampleAge) && sampleAge >= 0
    && sampleAge <= maximumSampleAge
  if (sampleIsFresh && sampledSpeed > nativeSpeed) {
    return { x: sampledVelocityX, y: sampledVelocityY, speed: sampledSpeed }
  }
  return { x: nativeVelocityX, y: nativeVelocityY, speed: nativeSpeed }
}

function advanceKineticRotation(state, elapsedSeconds, options) {
  var current = state || ({})
  var config = options || ({})
  var longitude = Number(current.longitude)
  var latitude = Number(current.latitude)
  var velocityX = Number(current.velocityX)
  var velocityY = Number(current.velocityY)
  var elapsed = Number(elapsedSeconds)
  if (!isFinite(longitude)) longitude = 0
  if (!isFinite(latitude)) latitude = 0
  if (!isFinite(velocityX)) velocityX = 0
  if (!isFinite(velocityY)) velocityY = 0

  var speed = Math.sqrt(velocityX * velocityX + velocityY * velocityY)
  if (!isFinite(speed) || speed <= 0 || !isFinite(elapsed) || elapsed <= 0) {
    return {
      longitude: wrapLongitude(longitude),
      latitude: latitude,
      velocityX: velocityX,
      velocityY: velocityY,
      deltaX: 0,
      deltaY: 0,
      active: speed > 0
    }
  }

  var deceleration = Number(config.deceleration)
  if (!isFinite(deceleration) || deceleration < 0) deceleration = 0
  var activeTime = deceleration > 0 ? Math.min(elapsed, speed / deceleration) : elapsed
  var nextSpeed = Math.max(0, speed - deceleration * activeTime)
  var distance = (speed + nextSpeed) * activeTime / 2
  var directionX = velocityX / speed
  var directionY = velocityY / speed
  var deltaX = directionX * distance
  var deltaY = directionY * distance

  var scale = Number(config.scale)
  if (!isFinite(scale) || scale <= 0) scale = 1
  var longitudeSensitivity = Number(config.longitudeSensitivity)
  var latitudeSensitivity = Number(config.latitudeSensitivity)
  if (!isFinite(longitudeSensitivity)) longitudeSensitivity = 0
  if (!isFinite(latitudeSensitivity)) latitudeSensitivity = 0
  var minimumLatitude = Number(config.minimumLatitude)
  var maximumLatitude = Number(config.maximumLatitude)
  if (!isFinite(minimumLatitude)) minimumLatitude = -78
  if (!isFinite(maximumLatitude)) maximumLatitude = 78

  var nextLongitude = wrapLongitude(longitude - deltaX * longitudeSensitivity / scale)
  var nextLatitude = clamp(
    latitude + deltaY * latitudeSensitivity / scale,
    minimumLatitude, maximumLatitude)
  var nextVelocityX = directionX * nextSpeed
  var nextVelocityY = directionY * nextSpeed
  if ((nextLatitude >= maximumLatitude && nextVelocityY > 0)
      || (nextLatitude <= minimumLatitude && nextVelocityY < 0))
    nextVelocityY = 0

  var remainingSpeed = Math.sqrt(
    nextVelocityX * nextVelocityX + nextVelocityY * nextVelocityY)
  return {
    longitude: nextLongitude,
    latitude: nextLatitude,
    velocityX: nextVelocityX,
    velocityY: nextVelocityY,
    deltaX: deltaX,
    deltaY: deltaY,
    active: remainingSpeed > 1e-9
  }
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

function countryCentre(features, code) {
  var rows = Array.isArray(features) ? features : []
  var wanted = String(code || "").toUpperCase()

  for (var i = 0; i < rows.length; i++) {
    var feature = rows[i]
    if (!feature || !feature.geometry || !feature.properties) continue
    if (String(feature.properties.code || "").toUpperCase() !== wanted) continue

    var geometry = feature.geometry
    var polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates
    if (!Array.isArray(polygons)) return null

    var best = null
    for (var p = 0; p < polygons.length; p++) {
      var ring = polygons[p] && polygons[p][0]
      if (!Array.isArray(ring) || ring.length < 3) continue

      var points = []
      var previousLongitude = Number(ring[0][0])
      for (var n = 0; n < ring.length; n++) {
        var longitude = Number(ring[n][0])
        var latitude = Number(ring[n][1])
        if (!isFinite(longitude) || !isFinite(latitude)) continue
        if (points.length > 0) {
          while (longitude - previousLongitude > 180) longitude -= 360
          while (longitude - previousLongitude < -180) longitude += 360
        }
        points.push([longitude, latitude])
        previousLongitude = longitude
      }
      if (points.length < 3) continue

      var crossSum = 0
      var longitudeSum = 0
      var latitudeSum = 0
      for (var pointIndex = 0, previous = points.length - 1;
           pointIndex < points.length; previous = pointIndex++) {
        var first = points[previous]
        var second = points[pointIndex]
        var cross = first[0] * second[1] - second[0] * first[1]
        crossSum += cross
        longitudeSum += (first[0] + second[0]) * cross
        latitudeSum += (first[1] + second[1]) * cross
      }

      var area = Math.abs(crossSum)
      if (area < 1e-9 || (best && area <= best.area)) continue
      best = {
        area: area,
        latitude: latitudeSum / (3 * crossSum),
        longitude: wrapLongitude(longitudeSum / (3 * crossSum))
      }
    }

    return best ? { latitude: best.latitude, longitude: best.longitude } : null
  }

  return null
}

function estimatedCountryLocation(features, code, key) {
  var rows = Array.isArray(features) ? features : []
  var wanted = String(code || "").toUpperCase()
  var cacheKey = "$" + wanted + ":" + String(key || wanted)
  if (estimatedLocationCache[cacheKey] !== undefined)
    return estimatedLocationCache[cacheKey]
  var bestRing = null
  var bestArea = 0

  for (var i = 0; i < rows.length; i++) {
    var feature = rows[i]
    if (!feature || !feature.geometry || !feature.properties) continue
    if (String(feature.properties.code || "").toUpperCase() !== wanted) continue

    var geometry = feature.geometry
    var polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates
    if (!Array.isArray(polygons)) break
    for (var p = 0; p < polygons.length; p++) {
      var ring = polygons[p] && polygons[p][0]
      if (!Array.isArray(ring) || ring.length < 3) continue
      var points = []
      var previousLongitude = Number(ring[0][0])
      for (var pointIndex = 0; pointIndex < ring.length; pointIndex++) {
        var longitude = Number(ring[pointIndex][0])
        var latitude = Number(ring[pointIndex][1])
        if (!isFinite(longitude) || !isFinite(latitude)) continue
        if (points.length > 0) {
          while (longitude - previousLongitude > 180) longitude -= 360
          while (longitude - previousLongitude < -180) longitude += 360
        }
        points.push([longitude, latitude])
        previousLongitude = longitude
      }
      if (points.length < 3) continue

      var area = 0
      for (var n = 0, previous = points.length - 1; n < points.length; previous = n++)
        area += points[previous][0] * points[n][1] - points[n][0] * points[previous][1]
      area = Math.abs(area)
      if (area > bestArea) {
        bestArea = area
        bestRing = points
      }
    }
    break
  }

  if (!bestRing) return null
  var minimumLongitude = Infinity
  var maximumLongitude = -Infinity
  var minimumLatitude = Infinity
  var maximumLatitude = -Infinity
  for (var boundIndex = 0; boundIndex < bestRing.length; boundIndex++) {
    minimumLongitude = Math.min(minimumLongitude, bestRing[boundIndex][0])
    maximumLongitude = Math.max(maximumLongitude, bestRing[boundIndex][0])
    minimumLatitude = Math.min(minimumLatitude, bestRing[boundIndex][1])
    maximumLatitude = Math.max(maximumLatitude, bestRing[boundIndex][1])
  }

  var seed = 2166136261
  var source = String(key || wanted)
  for (var character = 0; character < source.length; character++) {
    seed ^= source.charCodeAt(character)
    seed = Math.imul(seed, 16777619)
  }
  seed >>>= 0

  function random() {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }

  for (var attempt = 0; attempt < 96; attempt++) {
    var candidateLongitude = minimumLongitude
      + random() * (maximumLongitude - minimumLongitude)
    var candidateLatitude = minimumLatitude
      + random() * (maximumLatitude - minimumLatitude)
    if (pointInRing(candidateLongitude, candidateLatitude, bestRing)) {
      var location = {
        latitude: candidateLatitude,
        longitude: wrapLongitude(candidateLongitude)
      }
      estimatedLocationCache[cacheKey] = location
      return location
    }
  }
  var centre = countryCentre(features, wanted)
  if (centre) estimatedLocationCache[cacheKey] = centre
  return centre
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

function nearestVisibleStation(stations, centreLatitude, centreLongitude, excludedUuid,
                               width, height, scale) {
  var rows = Array.isArray(stations) ? stations : []
  var excluded = String(excludedUuid || "")
  var viewportWidth = Number(width)
  var viewportHeight = Number(height)
  var viewportScale = Number(scale)
  var constrainToViewport = isFinite(viewportWidth) && viewportWidth > 0
    && isFinite(viewportHeight) && viewportHeight > 0
    && isFinite(viewportScale) && viewportScale > 0
  var viewportRadius = constrainToViewport
    ? Math.min(viewportWidth, viewportHeight) * 0.44 * viewportScale : 0
  var nearest = null
  var nearestDepth = -Infinity
  var preferred = null
  var preferredDepth = -Infinity

  for (var i = 0; i < rows.length; i++) {
    var station = rows[i]
    if (!station || station.latitude === null || station.longitude === null) continue
    var latitude = Number(station.latitude)
    var longitude = Number(station.longitude)
    if (!isFinite(latitude) || !isFinite(longitude)) continue
    var point = project(latitude, longitude, centreLatitude, centreLongitude)
    if (!isFinite(point.z) || point.z < 0) continue
    if (constrainToViewport) {
      var screenX = viewportWidth / 2 + point.x * viewportRadius
      var screenY = viewportHeight / 2 - point.y * viewportRadius
      if (screenX < 0 || screenX > viewportWidth
          || screenY < 0 || screenY > viewportHeight)
        continue
    }
    if (point.z > nearestDepth) {
      nearest = station
      nearestDepth = point.z
    }
    if (String(station.uuid || "") !== excluded && point.z > preferredDepth) {
      preferred = station
      preferredDepth = point.z
    }
  }

  return preferred || nearest
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

function mergeGeoStations(primary, secondary, countries) {
  var rows = mergeStations(primary, secondary, 5500)
  var output = []
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i]
    if (row.latitude === null || row.longitude === null) {
      var estimate = estimatedCountryLocation(countries, row.countryCode, row.uuid)
      if (!estimate) continue
      var estimated = ({})
      for (var key in row) estimated[key] = row[key]
      estimated.latitude = estimate.latitude
      estimated.longitude = estimate.longitude
      estimated.estimatedLocation = true
      output.push(estimated)
    } else {
      output.push(row)
    }
    if (output.length >= 5500) break
  }
  return output
}

function combineStations(groups, maximum, replaceDuplicates) {
  var output = []
  var seen = ({})
  var limit = Math.max(1, Number(maximum || 500))

  for (var g = 0; g < groups.length; g++) {
    var rows = Array.isArray(groups[g]) ? groups[g] : []
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i]
      if (!row || !row.uuid) continue
      var key = "$" + row.uuid
      if (seen[key] !== undefined) {
        if (replaceDuplicates && g > 0) output[seen[key]] = row
        continue
      }
      if (output.length >= limit) continue
      seen[key] = output.length
      output.push(row)
    }
  }
  return output
}

function mergeStations(primary, secondary, maximum) {
  return combineStations([primary, secondary], maximum, true)
}

function prioritizeStations(priority, fallback, maximum) {
  return combineStations([priority, fallback], maximum, false)
}

function searchStations(stations, query, maximum) {
  var rows = Array.isArray(stations) ? stations : []
  var wanted = String(query || "").trim().toLowerCase()
  if (!wanted) return []

  var output = []
  var limit = Math.max(1, Number(maximum || 150))
  for (var i = 0; i < rows.length && output.length < limit; i++) {
    var station = rows[i]
    if (!station) continue
    var fields = [
      station.name,
      station.country,
      station.countryCode,
      station.state,
      station.language,
      station.tags,
      station.codec
    ]
    for (var fieldIndex = 0; fieldIndex < fields.length; fieldIndex++) {
      if (String(fields[fieldIndex] || "").toLowerCase().indexOf(wanted) < 0) continue
      output.push(station)
      break
    }
  }
  return output
}

function stationsForCountry(stations, code, maximum) {
  var rows = Array.isArray(stations) ? stations : []
  var wanted = String(code || "").toUpperCase()
  if (!wanted) return []

  var output = []
  var limit = Math.max(1, Number(maximum || 150))
  for (var i = 0; i < rows.length && output.length < limit; i++) {
    if (String(rows[i] && rows[i].countryCode || "").toUpperCase() === wanted)
      output.push(rows[i])
  }
  return output
}

function stationWindow(stations, uuid, maximum) {
  var rows = Array.isArray(stations) ? stations : []
  var index = indexByUuid(rows, uuid)
  if (index < 0) return []

  var limit = Math.min(rows.length, Math.max(1, Number(maximum || 500)))
  var before = Math.floor((limit - 1) / 2)
  var start = (index - before + rows.length) % rows.length
  var output = []
  for (var i = 0; i < limit; i++) output.push(rows[(start + i) % rows.length])
  return output
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
