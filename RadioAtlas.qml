import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "RadioModel.js" as RadioModel

Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property var countries: []
  property var worldStations: []
  property var results: []
  property var favorites: []
  property var recent: []
  property string mode: "world"
  property string activeCountryCode: ""
  property string activeCountryName: ""
  property int selectedIndex: -1
  property var selectedStation: null
  property bool keyboardSelectionVisible: false

  property bool fetching: false
  property string fetchAction: ""
  property string fetchValue: ""
  property string pendingFetchAction: ""
  property string pendingFetchValue: ""
  property string fetchError: ""
  property string fetchOutput: ""
  property string fetchStderr: ""
  property string worldExpandOutput: ""
  readonly property int worldStationLimit: 5000

  property bool playerRunning: false
  property bool playerPaused: false
  property bool playerMuted: false
  property int playerVolume: 70
  property int reportedVolume: 70
  property int pendingVolume: -1
  property string playerTitle: ""
  property var playingStation: null
  property string playingStationUuid: ""
  property string recordedStationUuid: ""
  property string lastRandomUuid: ""
  property bool playCancellationRequested: false
  property var pendingPlayStation: null
  property string pendingPlayScope: ""
  property var pendingPlayStations: []
  property bool statusReady: false
  readonly property bool playPreparing: playerActionProcess.running
    && playerActionProcess.action === "play"
  readonly property bool playerActionBusy: playerActionProcess.running || stopProcess.running
  property int playlistPosition: -1
  property int playlistCount: 0
  property string playerError: ""
  property string localError: ""
  property bool localReloadPending: false
  property var pendingFavoriteRequests: []
  property string pendingRecentUuid: ""

  readonly property string fetchPath: Qt.resolvedUrl("radio-fetch").toString().replace(/^file:\/\//, "")
  readonly property string playerPath: Qt.resolvedUrl("radio-player").toString().replace(/^file:\/\//, "")
  readonly property string statePath: Qt.resolvedUrl("radio-state").toString().replace(/^file:\/\//, "")
  readonly property string runtimePath: Quickshell.env("XDG_RUNTIME_DIR") + "/omarchy-radio-atlas"
  readonly property string statusPath: runtimePath + "/status.json"
  readonly property string playSelectionPath: runtimePath + "/play-selection.json"
  readonly property string favoriteSelectionPath: runtimePath + "/favorite-selection.json"

  readonly property var displayStations: mode === "favorites"
    ? favorites
    : (mode === "recent" ? recent : results)
  readonly property var currentGeoStations:
    RadioModel.mergeGeoStations(worldStations, displayStations, countries)
  readonly property string playingStationName: playingStation
    ? String(playingStation.name || "").trim() : ""
  readonly property string playingTrackTitle: {
    var title = String(playerTitle || "").trim()
    var station = playingStationName.toLowerCase()
    return title && station && title.toLowerCase() !== station ? title : ""
  }
  readonly property bool remoteMode: mode !== "favorites" && mode !== "recent"
  readonly property bool lightTheme:
    0.2126 * background.r + 0.7152 * background.g + 0.0722 * background.b > 0.5

  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property color accent: Color.accent
  property color urgent: Color.urgent
  property color dim: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.56)
  property color faint: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.12)
  property color favoriteColor: lightTheme ? "#8a6100" : "#f2c94c"
  property color mapBackground: lightTheme ? "#e7e6e1" : "#090a0c"
  property color mapSphere: lightTheme ? "#d2d0ca" : "#11151a"
  property color mapLand: lightTheme ? "#a9aaa6" : "#283039"
  property color mapGrid: lightTheme ? "#3f454a" : "#7d8791"

  readonly property int cardWidth: Math.min(Style.space(1180), panel.width - Style.gapsOut * 2)
  readonly property int cardHeight: Math.min(Style.space(760), panel.height - Style.gapsOut * 2)
  readonly property int headerHeight: Style.space(68)
  readonly property int sidebarWidth: Math.min(Style.space(390), cardWidth * 0.39)

  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (error) { payload = ({}) }

    opened = true
    fetchError = ""
    loadState()
    if (payload.action === "random") {
      if (worldStations.length === 0) showWorld()
      tuneRandom()
    } else if (worldStations.length === 0) showWorld()
    scheduleWorldExpansion(800)
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    opened = false
    worldExpandTimer.stop()
    if (worldExpandProcess.running) worldExpandProcess.running = false
  }

  function dismiss() {
    close()
    if (shell && typeof shell.hide === "function")
      shell.hide((manifest && manifest.id) || "akshar.radio-atlas")
  }

  function handleHyprlandEvent(event) {
    if (!opened || String(event && event.name || "") !== "openwindow") return
    var parts = []
    try {
      parts = event.parse(4)
    } catch (error) {
      parts = String(event && event.data || "").split(",")
    }
    if (String(parts[2] || "") === "org.omarchy.screensaver") dismiss()
  }

  function highlightStationCountry(station, focusGlobe) {
    if (!station) {
      activeCountryCode = ""
      activeCountryName = ""
      return
    }
    activeCountryCode = String(station.countryCode || "").toUpperCase()
    activeCountryName = String(station.country || activeCountryCode)
    if (focusGlobe !== true) return
    var latitude = Number(station.latitude)
    var longitude = Number(station.longitude)
    if (station.latitude !== null && station.longitude !== null
        && isFinite(latitude) && isFinite(longitude)) {
      globe.focusCoordinate(latitude, longitude)
    } else if (activeCountryCode) {
      globe.focusCountry(activeCountryCode)
    }
  }

  function restorePlayingCountry(focusGlobe) {
    if (playerRunning && playingStation) {
      highlightStationCountry(playingStation, focusGlobe === true)
      return
    }
    activeCountryCode = ""
    activeCountryName = ""
  }

  function setSelection(index, fromKeyboard) {
    keyboardSelectionVisible = fromKeyboard === true
    var stations = displayStations
    if (!Array.isArray(stations) || stations.length === 0) {
      selectedIndex = -1
      selectedStation = null
      return
    }
    selectedIndex = Math.max(0, Math.min(stations.length - 1, index))
    selectedStation = stations[selectedIndex]
    stationList.currentIndex = selectedIndex
    stationList.positionViewAtIndex(selectedIndex, ListView.Contain)
  }

  function moveSelection(delta) {
    if (displayStations.length === 0) return
    if (selectedIndex < 0) setSelection(delta < 0 ? displayStations.length - 1 : 0, true)
    else setSelection((selectedIndex + delta + displayStations.length) % displayStations.length, true)
  }

  function setStationList(nextMode, stations) {
    mode = nextMode
    if (nextMode !== "favorites" && nextMode !== "recent") results = stations
    setSelection(stations.length > 0 ? 0 : -1)
  }

  function scheduleWorldExpansion(delay) {
    if (!opened || worldStations.length === 0
        || worldStations.length >= worldStationLimit) return
    worldExpandTimer.interval = Math.max(500, Number(delay || 1600))
    worldExpandTimer.restart()
  }

  function cancelPendingFetch() {
    pendingFetchAction = ""
    pendingFetchValue = ""
  }

  function cancelPendingPlay() {
    pendingPlayStation = null
    pendingPlayScope = ""
    pendingPlayStations = []
  }

  function startFetch(action, value) {
    var nextValue = value || ""
    if (fetchProcess.running) {
      if (fetchAction === action && fetchValue === nextValue) {
        cancelPendingFetch()
        return
      }
      if (pendingFetchAction === action && pendingFetchValue === nextValue) return
      pendingFetchAction = action
      pendingFetchValue = nextValue
      fetching = true
      return
    }
    fetching = true
    fetchAction = action
    fetchValue = nextValue
    fetchError = ""
    fetchOutput = ""
    fetchStderr = ""
    fetchProcess.command = nextValue ? [fetchPath, action, nextValue] : [fetchPath, action]
    fetchProcess.running = true
  }

  function showWorld(refresh) {
    searchDebounce.stop()
    cancelPendingFetch()
    searchField.text = ""
    restorePlayingCountry(false)
    fetchError = ""
    localError = ""
    setStationList("world", worldStations)
    if (refresh !== false) startFetch("world", "")
  }

  function showFavorites() {
    searchDebounce.stop()
    cancelPendingFetch()
    searchField.text = ""
    mode = "favorites"
    restorePlayingCountry(true)
    fetchError = ""
    localError = ""
    setSelection(favorites.length > 0 ? 0 : -1)
  }

  function showRecent() {
    searchDebounce.stop()
    cancelPendingFetch()
    searchField.text = ""
    mode = "recent"
    restorePlayingCountry(true)
    fetchError = ""
    localError = ""
    setSelection(recent.length > 0 ? 0 : -1)
  }

  function previewSearch(text) {
    var query = String(text || "").trim()
    if (!query) {
      showWorld()
      return false
    }
    restorePlayingCountry(false)
    fetchError = ""
    setStationList("search", RadioModel.searchStations(worldStations, query))
    return true
  }

  function search(text) {
    var query = String(text || "").trim()
    if (!previewSearch(query)) return
    startFetch("search", query)
  }

  function browseCountry(code, name) {
    var countryCode = String(code || "").toUpperCase()
    if (!/^[A-Z]{2}$/.test(countryCode)) return
    var countryName = String(name || "")
    if (!countryName) {
      for (var i = 0; i < countries.length; i++) {
        var properties = countries[i] && countries[i].properties
        if (String(properties && properties.code || "").toUpperCase() !== countryCode) continue
        countryName = String(properties.name || "")
        break
      }
    }
    if (!countryName) countryName = countryCode
    searchDebounce.stop()
    cancelPendingFetch()
    var cachedStations = RadioModel.stationsForCountry(worldStations, countryCode)
    worldStations = RadioModel.prioritizeStations(
      cachedStations, worldStations, worldStationLimit)
    setStationList("country", cachedStations)
    activeCountryCode = countryCode
    activeCountryName = countryName
    fetchError = ""
    searchField.text = countryName
    startFetch("country", countryCode)
    keyCatcher.forceActiveFocus()
  }

  function tuneRandom() {
    searchDebounce.stop()
    cancelPendingFetch()
    searchField.text = ""
    setStationList("random", [])
    restorePlayingCountry(false)
    fetchError = ""
    startFetch("random", randomExclusions())
  }

  function randomExclusions() {
    var output = []
    var seen = ({})

    function append(uuid) {
      var value = String(uuid || "")
      if (!/^[0-9A-Fa-f-]{20,64}$/.test(value) || seen["$" + value]) return
      seen["$" + value] = true
      output.push(value)
    }

    append(playingStationUuid)
    append(lastRandomUuid)
    for (var i = 0; i < recent.length && output.length < 32; i++)
      append(recent[i] && recent[i].uuid)
    return output.join(",")
  }

  function activateMapStation(station) {
    var index = RadioModel.indexByUuid(displayStations, station.uuid)
    if (index < 0) {
      index = RadioModel.indexByUuid(worldStations, station.uuid)
      if (index < 0) return
      showWorld(false)
    }
    setSelection(index)
    playSelected()
  }

  function playlistScope() {
    if (mode === "world") return "world"
    if (mode === "favorites") return "favorites"
    if (mode === "recent") return "recent"
    return "results"
  }

  function playSelected() {
    if (!selectedStation) return
    playStation(selectedStation, playlistScope(), displayStations)
  }

  function writeSelection(fileView, station, stations) {
    var rows = RadioModel.stationWindow(stations, station && station.uuid, 500)
    if (rows.length === 0) return false
    fileView.setText(JSON.stringify(rows) + "\n")
    return true
  }

  function playStation(station, scope, stations) {
    if (!station) return
    if (playerActionBusy) {
      pendingPlayStation = station
      pendingPlayScope = scope
      pendingPlayStations = Array.isArray(stations) ? stations.slice(0) : []
      return
    }
    cancelPendingPlay()
    var playerScope = scope
    if (scope === "world" || scope === "results") {
      if (!writeSelection(playSelectionFile, station, stations)) {
        playerError = "Could not prepare this station"
        return
      }
      playerScope = "selection"
    }
    playCancellationRequested = false
    highlightStationCountry(station, true)
    playerError = ""
    playerActionProcess.action = "play"
    playerActionProcess.output = ""
    playerActionProcess.errorOutput = ""
    playerActionProcess.command = [playerPath, "play", station.uuid, playerScope]
    playerActionProcess.running = true
  }

  function playPendingStation() {
    if (!pendingPlayStation || playerActionBusy) return
    var station = pendingPlayStation
    var scope = pendingPlayScope
    var stations = pendingPlayStations
    cancelPendingPlay()
    playStation(station, scope, stations)
  }

  function playerAction(action) {
    if (playerActionBusy) return
    playerError = ""
    playerActionProcess.action = action
    playerActionProcess.output = ""
    playerActionProcess.errorOutput = ""
    playerActionProcess.command = [playerPath, action]
    playerActionProcess.running = true
  }

  function stopPlayer() {
    cancelPendingPlay()
    if (stopProcess.running || playCancellationRequested) return
    if (playerActionProcess.running && !playPreparing) return
    if (playPreparing) playCancellationRequested = true
    playerError = ""
    stopProcess.command = [playerPath, "stop"]
    stopProcess.running = true
  }

  function applyPlayerState(raw) {
    try {
      if (typeof raw !== "string" || raw.length > 65536)
        throw new Error("Player status is too large")
      var state = JSON.parse(raw || "{}")
      var previousUuid = playingStationUuid
      var nextPlayingStation = state.station && typeof state.station === "object"
        && String(state.station.uuid || "") ? state.station : null
      var nextPlayingUuid = nextPlayingStation ? String(nextPlayingStation.uuid) : ""
      playerRunning = state.running === true
      playerPaused = state.paused === true
      playerMuted = state.muted === true
      var nextVolume = Math.round(Number(state.volume === undefined ? 70 : state.volume))
      reportedVolume = isFinite(nextVolume) ? Math.max(0, Math.min(100, nextVolume)) : 70
      if (pendingVolume < 0) playerVolume = reportedVolume
      playerTitle = String(state.title || (nextPlayingStation && nextPlayingStation.name) || "")
        .replace(/[\r\n\t]+/g, " ").slice(0, 512)
      playlistPosition = Number(state.playlistPosition === undefined ? -1 : state.playlistPosition)
      playlistCount = Number(state.playlistCount || 0)

      var playingChanged = playerRunning && nextPlayingUuid && nextPlayingUuid !== previousUuid
      playingStation = nextPlayingStation
      playingStationUuid = playerRunning ? nextPlayingUuid : ""
      if (playerError === "Player status is unavailable") playerError = ""
      if (!playerRunning) recordedStationUuid = ""

      var matchingIndex = nextPlayingUuid
        ? RadioModel.indexByUuid(displayStations, nextPlayingUuid) : -1
      if (matchingIndex < 0 && playerTitle) {
        for (var i = 0; i < displayStations.length; i++) {
          if (displayStations[i].name === playerTitle) { matchingIndex = i; break }
        }
      }
      if (matchingIndex >= 0) {
        selectedIndex = matchingIndex
        selectedStation = displayStations[matchingIndex]
      }

      var countryStation = nextPlayingStation || (matchingIndex >= 0 ? selectedStation : null)
      if (playerRunning && playingChanged && countryStation)
        highlightStationCountry(countryStation, true)
      if (state.loaded === true && nextPlayingUuid && nextPlayingUuid !== recordedStationUuid) {
        recordedStationUuid = nextPlayingUuid
        recordPlayed(nextPlayingUuid)
      }
    } catch (error) {
      playerError = "Player status is unavailable"
    }
  }

  function setPlayerVolume(value) {
    pendingVolume = Math.max(0, Math.min(100, Math.round(value)))
    playerVolume = pendingVolume
    playerError = ""
    volumeTimer.restart()
  }

  function changePlayerVolume(delta) {
    var current = pendingVolume >= 0 ? pendingVolume : playerVolume
    setPlayerVolume(current + delta)
  }

  function flushPlayerVolume() {
    if (stopProcess.running) {
      volumeTimer.restart()
      return
    }
    if (volumeProcess.running || pendingVolume < 0) return
    volumeProcess.submittedVolume = pendingVolume
    volumeProcess.output = ""
    volumeProcess.errorOutput = ""
    volumeProcess.command = [root.playerPath, "volume", String(pendingVolume)]
    volumeProcess.running = true
  }

  function loadState() {
    if (stateProcess.running) {
      localReloadPending = true
      return
    }
    localReloadPending = false
    stateProcess.action = "get"
    stateProcess.output = ""
    stateProcess.errorOutput = ""
    stateProcess.command = [statePath, "get"]
    stateProcess.running = true
  }

  function requestLocalStateReload() {
    localReloadPending = true
    Qt.callLater(reloadLocalStateWhenIdle)
  }

  function reloadLocalStateWhenIdle() {
    if (!localReloadPending || stateProcess.running || historyProcess.running
        || pendingFavoriteRequests.length > 0 || pendingRecentUuid) return
    loadState()
  }

  function applyLocalState(raw) {
    try {
      var state = JSON.parse(raw || "{}")
      favorites = Array.isArray(state.favorites) ? state.favorites : []
      recent = Array.isArray(state.recent) ? state.recent : []
      localError = ""
    } catch (error) {
      localError = "Saved stations could not be loaded"
    }
  }

  function isFavorite(uuid) {
    return RadioModel.indexByUuid(favorites, uuid) >= 0
  }

  function toggleFavorite(uuid) {
    if (!uuid) return
    localError = ""
    var request = { uuid: uuid, rows: [] }
    var index = RadioModel.indexByUuid(displayStations, uuid)
    if (remoteMode && index >= 0) {
      request.rows = RadioModel.stationWindow(displayStations, uuid, 500)
      if (request.rows.length === 0) {
        localError = "Favorite could not be updated"
        return
      }
    }
    if (stateProcess.running) {
      pendingFavoriteRequests = pendingFavoriteRequests.concat([request])
      return
    }
    startFavorite(request)
  }

  function startFavorite(request) {
    if (request.rows.length > 0)
      favoriteSelectionFile.setText(JSON.stringify(request.rows) + "\n")
    stateProcess.action = "favorite"
    stateProcess.output = ""
    stateProcess.errorOutput = ""
    stateProcess.command = [statePath, "favorite", request.uuid]
    stateProcess.running = true
  }

  function recordPlayed(uuid) {
    if (!uuid) return
    if (historyProcess.running) {
      pendingRecentUuid = uuid
      return
    }
    startRecordPlayed(uuid)
  }

  function startRecordPlayed(uuid) {
    historyProcess.output = ""
    historyProcess.errorOutput = ""
    historyProcess.command = [statePath, "played", uuid]
    historyProcess.running = true
  }

  function refreshLocalSelection() {
    if (mode !== "favorites" && mode !== "recent") return
    var stations = displayStations
    var preferredUuid = selectedStation ? selectedStation.uuid : playingStationUuid
    var index = preferredUuid ? RadioModel.indexByUuid(stations, preferredUuid) : -1
    if (index < 0 && stations.length > 0) index = Math.min(Math.max(selectedIndex, 0), stations.length - 1)
    setSelection(index)
  }

  function emptyStateText() {
    if (fetchError) return fetchError
    if (localError) return localError
    if (mode === "favorites") return "No favorites yet. Select a station and press F."
    if (mode === "recent") return "No listening history yet."
    if (mode === "search") return "No stations match “" + String(searchField.text || "").trim() + "”."
    if (mode === "country") return "No working stations found in " + (activeCountryName || "this country") + "."
    return "No working stations found."
  }

  FileView {
    path: Qt.resolvedUrl("assets/countries.json").toString().replace(/^file:\/\//, "")
    watchChanges: false
    printErrors: true
    onLoaded: {
      try {
        var collection = JSON.parse(text())
        root.countries = Array.isArray(collection.features) ? collection.features : []
      } catch (error) {
        root.countries = []
        root.fetchError = "Map data could not be loaded"
      }
    }
  }

  FileView {
    path: root.statusReady ? root.statusPath : ""
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.applyPlayerState(text())
    onFileChanged: reload()
  }

  FileView {
    id: playSelectionFile
    path: root.playSelectionPath
    preload: false
    watchChanges: false
    blockWrites: true
    atomicWrites: true
    printErrors: true
    onSaveFailed: root.playerError = "Could not prepare this station"
  }

  FileView {
    id: favoriteSelectionFile
    path: root.favoriteSelectionPath
    preload: false
    watchChanges: false
    blockWrites: true
    atomicWrites: true
    printErrors: true
    onSaveFailed: root.localError = "Favorite could not be updated"
  }

  Process {
    id: statusInitProcess
    command: []
    onExited: function(exitCode) {
      if (exitCode === 0) root.statusReady = true
    }
  }

  Process {
    id: fetchProcess
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.fetchOutput = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.fetchStderr = text
    }
    onExited: function(exitCode) {
      var completedOutput = root.fetchOutput
      root.fetchOutput = ""
      var stations = null
      if (exitCode === 0) {
        try {
          var parsed = JSON.parse(completedOutput || "[]")
          if (Array.isArray(parsed)) stations = parsed
        } catch (error) {
          stations = null
        }
      }
      if (root.fetchAction === "world" && stations !== null)
        root.worldStations = RadioModel.mergeStations(
          root.worldStations, stations, root.worldStationLimit)
      if (root.fetchAction === "world" && stations !== null)
        root.scheduleWorldExpansion(1200)

      if (root.pendingFetchAction) {
        var nextAction = root.pendingFetchAction
        var nextValue = root.pendingFetchValue
        root.pendingFetchAction = ""
        root.pendingFetchValue = ""
        root.fetching = false
        Qt.callLater(function() {
          if (root.mode === nextAction)
            root.startFetch(nextAction,
              nextAction === "random" ? root.randomExclusions() : nextValue)
        })
        return
      }

      root.fetching = false
      if (root.mode !== root.fetchAction) return
      if (root.fetchAction === "search"
          && String(searchField.text || "").trim() !== root.fetchValue) return
      if (exitCode !== 0) {
        root.fetchError = root.displayStations.length > 0
          ? "Showing cached stations · Radio Browser is unavailable"
          : "Radio Browser is unavailable. Try again shortly."
        return
      }
      if (stations === null) {
        root.fetchError = "Station data was not valid"
        return
      }
      root.fetchError = ""

      if (root.fetchAction === "world") {
        root.setStationList("world", root.worldStations)
      } else if (root.fetchAction === "country") {
        var countryStations = RadioModel.mergeStations(root.results, stations, 500)
        root.worldStations = RadioModel.prioritizeStations(
          countryStations, root.worldStations, root.worldStationLimit)
        root.setStationList("country", countryStations)
      } else if (root.fetchAction === "search") {
        root.setStationList("search", stations)
      } else if (root.fetchAction === "random") {
        root.setStationList("random", stations)
        if (stations.length > 0) {
          root.lastRandomUuid = String(stations[0].uuid || "")
          root.playSelected()
        }
      }

    }
  }

  Process {
    id: worldExpandProcess
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.worldExpandOutput = text
    }
    onExited: function(exitCode) {
      var output = root.worldExpandOutput
      root.worldExpandOutput = ""
      if (!root.opened) return
      if (exitCode !== 0) {
        root.scheduleWorldExpansion(30000)
        return
      }

      var stations = null
      try {
        var parsed = JSON.parse(output || "[]")
        if (Array.isArray(parsed)) stations = parsed
      } catch (error) {
        stations = null
      }
      if (stations === null || stations.length === 0) {
        root.scheduleWorldExpansion(30000)
        return
      }

      var merged = RadioModel.mergeStations(
        root.worldStations, stations, root.worldStationLimit)
      var added = merged.length - root.worldStations.length
      root.worldStations = merged
      if (root.mode === "world") root.results = merged
      root.scheduleWorldExpansion(added > 0 ? 1600 : 10000)
    }
  }

  Process {
    id: volumeProcess
    property int submittedVolume: -1
    property string output: ""
    property string errorOutput: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: volumeProcess.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: volumeProcess.errorOutput = text
    }
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        if (root.pendingVolume === submittedVolume) {
          root.pendingVolume = -1
          root.playerVolume = root.reportedVolume
        } else {
          Qt.callLater(root.flushPlayerVolume)
        }
        root.playerError = "Could not change volume"
        return
      }

      root.statusReady = true
      root.playerError = ""
      root.reportedVolume = submittedVolume
      if (root.pendingVolume === submittedVolume) {
        root.pendingVolume = -1
        root.playerVolume = submittedVolume
        return
      }
      Qt.callLater(root.flushPlayerVolume)
    }
  }

  Process {
    id: playerActionProcess
    property string action: ""
    property string output: ""
    property string errorOutput: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: playerActionProcess.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: playerActionProcess.errorOutput = text
    }
    onExited: function(exitCode) {
      var canceled = playerActionProcess.action === "play"
        && root.playCancellationRequested
      root.playCancellationRequested = false
      if (exitCode !== 0 && !canceled) {
        root.playerError = playerActionProcess.action === "play"
          ? "Could not play this station" : "Player action failed"
      }
      if (exitCode === 0) root.statusReady = true
      Qt.callLater(root.playPendingStation)
    }
  }

  Process {
    id: stopProcess
    command: []
    onExited: function(exitCode) {
      if (exitCode !== 0) root.playerError = "Could not stop the player"
      else root.statusReady = true
      Qt.callLater(root.playPendingStation)
    }
  }

  Process {
    id: stateProcess
    property string action: ""
    property string output: ""
    property string errorOutput: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: stateProcess.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: stateProcess.errorOutput = text
    }
    onExited: function(exitCode) {
      if (exitCode === 0) {
        if (stateProcess.action === "get") {
          root.applyLocalState(output)
          root.refreshLocalSelection()
        } else {
          root.localError = ""
          root.localReloadPending = true
        }
      } else {
        root.localError = stateProcess.action === "favorite"
          ? "Favorite could not be updated" : "Saved stations could not be loaded"
      }

      if (root.pendingFavoriteRequests.length > 0) {
        var nextRequest = root.pendingFavoriteRequests[0]
        root.pendingFavoriteRequests = root.pendingFavoriteRequests.slice(1)
        Qt.callLater(function() { root.startFavorite(nextRequest) })
        return
      }
      if (root.localReloadPending) root.requestLocalStateReload()
    }
  }

  Process {
    id: historyProcess
    property string output: ""
    property string errorOutput: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: historyProcess.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: historyProcess.errorOutput = text
    }
    onExited: function(exitCode) {
      if (exitCode === 0) {
        root.localError = ""
        root.localReloadPending = true
      } else {
        root.localError = "Listening history could not be updated"
      }

      if (root.pendingRecentUuid) {
        var nextUuid = root.pendingRecentUuid
        root.pendingRecentUuid = ""
        Qt.callLater(function() { root.startRecordPlayed(nextUuid) })
        return
      }
      if (root.localReloadPending) root.requestLocalStateReload()
    }
  }

  Timer {
    id: searchDebounce
    interval: 300
    repeat: false
    onTriggered: root.search(searchField.text)
  }

  Timer {
    id: worldExpandTimer
    interval: 1600
    repeat: false
    onTriggered: {
      if (!root.opened || worldExpandProcess.running
          || root.worldStations.length >= root.worldStationLimit) return
      root.worldExpandOutput = ""
      worldExpandProcess.command = [root.fetchPath, "world-more"]
      worldExpandProcess.running = true
    }
  }

  Timer {
    id: volumeTimer
    interval: 90
    repeat: false
    onTriggered: root.flushPlayerVolume()
  }

  Component.onCompleted: {
    statusInitProcess.command = [playerPath, "status"]
    statusInitProcess.running = true
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) { root.handleHyprlandEvent(event) }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    mask: Region { item: card }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-radio-atlas"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened && cardHover.hovered
      ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      anchors.centerIn: parent
      color: root.background
      borderSpec: Border.surfaceSpec("menu", "border", root.border, Math.max(1, Style.normalBorderWidth))
      radius: Style.cornerRadius

      MouseArea {
        id: cardMouse
        anchors.fill: parent
        onClicked: keyCatcher.forceActiveFocus()
      }

      HoverHandler {
        id: cardHover
        onHoveredChanged: if (hovered) keyCatcher.forceActiveFocus()
      }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true
        z: 1

        Keys.priority: Keys.AfterItem
        Keys.onPressed: function(event) {
          if (searchField.activeFocus) {
            if (event.key === Qt.Key_Escape) {
              if (searchField.text) {
                searchField.clear()
                root.showWorld()
              }
              else keyCatcher.forceActiveFocus()
              event.accepted = true
            }
            return
          }

          if (event.key === Qt.Key_Escape) {
            root.dismiss()
            event.accepted = true
          } else if (event.key === Qt.Key_Slash) {
            searchField.forceActiveFocus()
            searchField.selectAll()
            event.accepted = true
          } else if (event.key === Qt.Key_Up) {
            root.moveSelection(-1)
            event.accepted = true
          } else if (event.key === Qt.Key_Down) {
            root.moveSelection(1)
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.playSelected()
            event.accepted = true
          } else if (event.key === Qt.Key_Space) {
            if (root.playerRunning) root.playerAction("toggle")
            else root.playSelected()
            event.accepted = true
          } else if (event.key === Qt.Key_R) {
            root.tuneRandom()
            event.accepted = true
          } else if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) {
            root.changePlayerVolume(5)
            event.accepted = true
          } else if (event.key === Qt.Key_Minus) {
            root.changePlayerVolume(-5)
            event.accepted = true
          } else if (event.key === Qt.Key_M) {
            root.playerAction("mute")
            event.accepted = true
          } else if (event.key === Qt.Key_F && root.selectedStation) {
            root.toggleFavorite(root.selectedStation.uuid)
            event.accepted = true
          }
        }
      }

      Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.headerHeight
        z: 2

        Text {
          id: title
          anchors.left: parent.left
          anchors.leftMargin: Style.spacing.panelPadding
          anchors.verticalCenter: parent.verticalCenter
          text: "RADIO ATLAS"
          textFormat: Text.PlainText
          color: root.foreground
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        TextField {
          id: searchField
          anchors.right: randomButton.left
          anchors.rightMargin: Style.spacing.sm
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(Style.space(330), card.width * 0.32)
          placeholderText: "Search station, country, or genre"
          maximumLength: 128
          foreground: root.foreground
          accent: root.accent
          onTextEdited: {
            if (!root.previewSearch(text)) return
            searchDebounce.restart()
          }
          onAccepted: {
            searchDebounce.stop()
            root.search(text)
          }
        }

        Button {
          id: randomButton
          anchors.right: closeButton.left
          anchors.rightMargin: Style.spacing.xs
          anchors.verticalCenter: parent.verticalCenter
          iconText: "\uf074"
          tooltipText: "Tune randomly (R)"
          focusable: true
          foreground: root.foreground
          accent: root.accent
          onClicked: root.tuneRandom()
        }

        Button {
          id: closeButton
          anchors.right: parent.right
          anchors.rightMargin: Style.spacing.md
          anchors.verticalCenter: parent.verticalCenter
          iconText: "\uf00d"
          tooltipText: "Close"
          focusable: true
          foreground: root.foreground
          accent: root.accent
          onClicked: root.dismiss()
        }

        Rectangle {
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          height: 1
          color: root.faint
        }
      }

      Item {
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        z: 2

        Item {
          id: mapPane
          anchors.left: parent.left
          anchors.top: parent.top
          anchors.bottom: parent.bottom
          anchors.right: sidebar.left

          Globe {
            id: globe
            anchors.fill: parent
            anchors.margins: Style.spacing.lg
            countries: root.countries
            stations: root.currentGeoStations
            selectedStation: root.playingStation || root.selectedStation
            activeCountryCode: root.activeCountryCode
            backgroundColor: root.mapBackground
            sphereColor: root.mapSphere
            landColor: root.mapLand
            gridColor: root.mapGrid
            outlineColor: root.lightTheme ? "#3c4247" : "#9099a3"
            signalColor: root.lightTheme ? "#202428" : "#d9dee3"
            accentColor: root.accent
            textColor: root.foreground
            fontFamily: Style.font.menuFamily
            onInteractionStarted: {
              root.keyboardSelectionVisible = false
              keyCatcher.forceActiveFocus()
            }
            onPointerMoved: root.keyboardSelectionVisible = false
            onStationActivated: function(station) { root.activateMapStation(station) }
            onCountryActivated: function(code, name) { root.browseCountry(code, name) }
          }

          Text {
            id: mapHint
            anchors.left: parent.left
            anchors.leftMargin: Style.spacing.panelPadding
            anchors.right: signalCount.left
            anchors.rightMargin: Style.spacing.md
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.spacing.md
            text: root.fetchError || root.localError
              ? root.fetchError || root.localError
              : (root.activeCountryName
                ? root.activeCountryName + "  ·  click another country to browse"
                : "Drag to rotate  ·  wheel to zoom  ·  click a signal or country")
            textFormat: Text.PlainText
            color: root.fetchError || root.localError ? root.urgent : root.dim
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Text {
            id: signalCount
            anchors.right: parent.right
            anchors.rightMargin: Style.spacing.panelPadding
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.spacing.md
            text: root.currentGeoStations.length + " signals"
            textFormat: Text.PlainText
            color: root.dim
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
          }
        }

        Rectangle {
          anchors.top: parent.top
          anchors.bottom: parent.bottom
          anchors.right: sidebar.left
          width: 1
          color: root.faint
        }

        Item {
          id: sidebar
          width: root.sidebarWidth
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.bottom: parent.bottom

          Item {
            id: tabs
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: Style.space(48)

            Row {
              anchors.left: parent.left
              anchors.leftMargin: Style.spacing.md
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.spacing.xs

              Button {
                text: "World"
                selected: root.mode === "world"
                foreground: root.foreground
                accent: root.accent
                fontSize: Style.font.caption
                onClicked: root.showWorld()
              }
              Button {
                text: "Favorites"
                selected: root.mode === "favorites"
                foreground: root.foreground
                accent: root.accent
                fontSize: Style.font.caption
                onClicked: root.showFavorites()
              }
              Button {
                text: "Recent"
                selected: root.mode === "recent"
                foreground: root.foreground
                accent: root.accent
                fontSize: Style.font.caption
                onClicked: root.showRecent()
              }
            }

            Rectangle {
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.bottom: parent.bottom
              height: 1
              color: root.faint
            }
          }

          ListView {
            id: stationList
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: tabs.bottom
            anchors.bottom: playerPanel.top
            clip: true
            model: root.displayStations
            currentIndex: root.selectedIndex
            boundsBehavior: Flickable.StopAtBounds
            cacheBuffer: 500

            QQC.ScrollBar.vertical: QQC.ScrollBar {}

            delegate: Rectangle {
              id: stationRow
              required property var modelData
              required property int index

              width: stationList.width
              height: Style.space(64)
              color: root.playingStationUuid === stationRow.modelData.uuid
                ? Style.selectedFillFor(root.foreground, root.accent)
                : (rowMouse.containsMouse
                  ? Style.hoverFillFor(root.foreground, root.accent)
                  : "transparent")

              Accessible.name: modelData.name + ", " + RadioModel.stationMeta(modelData)
              Accessible.role: Accessible.ListItem
              Accessible.selected: root.selectedIndex === index
              Accessible.onPressAction: {
                root.setSelection(stationRow.index)
                root.playSelected()
              }

              Rectangle {
                visible: root.playingStationUuid === stationRow.modelData.uuid
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 2
                color: root.accent
              }

              Rectangle {
                anchors.fill: parent
                visible: root.keyboardSelectionVisible
                  && root.selectedIndex === stationRow.index
                  && root.playingStationUuid !== stationRow.modelData.uuid
                  && !rowMouse.containsMouse
                color: "transparent"
                border.color: root.accent
                border.width: 1
              }

              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.spacing.md
                anchors.right: favoriteButton.left
                anchors.rightMargin: Style.spacing.sm
                anchors.top: parent.top
                anchors.topMargin: Style.space(10)
                text: stationRow.modelData.name
                textFormat: Text.PlainText
                color: root.foreground
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.body
                font.bold: root.playingStationUuid === stationRow.modelData.uuid
                elide: Text.ElideRight
              }

              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.spacing.md
                anchors.right: favoriteButton.left
                anchors.rightMargin: Style.spacing.sm
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Style.space(9)
                text: RadioModel.stationMeta(stationRow.modelData)
                  + (RadioModel.compactTags(stationRow.modelData.tags, 2)
                    ? "  ·  " + RadioModel.compactTags(stationRow.modelData.tags, 2) : "")
                textFormat: Text.PlainText
                color: root.dim
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }

              Button {
                id: favoriteButton
                anchors.right: parent.right
                anchors.rightMargin: Style.spacing.sm
                anchors.verticalCenter: parent.verticalCenter
                iconText: root.isFavorite(stationRow.modelData.uuid) ? "\uf005" : "\uf006"
                tooltipText: root.isFavorite(stationRow.modelData.uuid) ? "Remove favorite" : "Add favorite"
                foreground: root.isFavorite(stationRow.modelData.uuid)
                  ? root.favoriteColor : root.foreground
                accent: root.accent
                onClicked: root.toggleFavorite(stationRow.modelData.uuid)
              }

              MouseArea {
                id: rowMouse
                anchors.left: parent.left
                anchors.right: favoriteButton.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onEntered: root.setSelection(stationRow.index)
                onClicked: {
                  root.setSelection(stationRow.index)
                  root.playSelected()
                  keyCatcher.forceActiveFocus()
                }
              }

              Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: root.faint
              }
            }

            Text {
              anchors.centerIn: parent
              width: parent.width - Style.spacing.panelPadding * 2
              visible: (!root.fetching || !root.remoteMode) && root.displayStations.length === 0
              text: root.emptyStateText()
              textFormat: Text.PlainText
              color: root.fetchError || root.localError ? root.urgent : root.dim
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.Wrap
            }

            Text {
              anchors.centerIn: parent
              visible: root.fetching && root.remoteMode && root.displayStations.length === 0
              text: "LOADING STATIONS"
              textFormat: Text.PlainText
              color: root.dim
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.caption
            }
          }

          Rectangle {
            id: playerPanel
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: Style.space(126)
            color: "transparent"

            Rectangle {
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: parent.top
              height: 1
              color: root.faint
            }

            Text {
              id: nowPlaying
              anchors.left: parent.left
              anchors.leftMargin: Style.spacing.md
              anchors.right: playingFavoriteButton.left
              anchors.rightMargin: Style.spacing.xs
              anchors.top: parent.top
              anchors.topMargin: Style.spacing.md
              text: root.playerRunning
                ? (root.playingStationName || root.playerTitle || "Unknown station")
                : "Nothing playing"
              textFormat: Text.PlainText
              color: root.foreground
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.body
              font.bold: root.playerRunning
              elide: Text.ElideRight
            }

            Text {
              anchors.left: nowPlaying.left
              anchors.right: nowPlaying.right
              anchors.top: nowPlaying.bottom
              anchors.topMargin: Style.spacing.xs
              text: root.playerError
                ? root.playerError
                : (!root.playerRunning ? "Choose a signal to begin"
                : (root.playingTrackTitle ? root.playingTrackTitle + "  ·  " : "")
                  + (root.playerPaused ? "Paused" : "Live")
                  + (root.playlistCount > 1 ? "  ·  " + root.playlistCount + " stations queued" : ""))
              textFormat: Text.PlainText
              color: root.playerError ? root.urgent : root.dim
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            Button {
              id: playingFavoriteButton
              anchors.right: parent.right
              anchors.rightMargin: Style.spacing.sm
              anchors.top: parent.top
              anchors.topMargin: Style.spacing.sm
              visible: root.playerRunning && root.playingStationUuid !== ""
              iconText: root.isFavorite(root.playingStationUuid) ? "\uf005" : "\uf006"
              tooltipText: root.isFavorite(root.playingStationUuid)
                ? "Remove playing station from favorites"
                : "Add playing station to favorites"
              focusable: true
              foreground: root.isFavorite(root.playingStationUuid)
                ? root.favoriteColor : root.foreground
              accent: root.accent
              Accessible.role: Accessible.Button
              Accessible.name: tooltipText
              onClicked: root.toggleFavorite(root.playingStationUuid)
            }

            Row {
              anchors.left: parent.left
              anchors.leftMargin: Style.spacing.sm
              anchors.bottom: parent.bottom
              anchors.bottomMargin: Style.spacing.sm
              spacing: Style.spacing.xs

              Button {
                iconText: "\uf048"
                tooltipText: "Previous station"
                enabled: root.playerRunning && !root.playerActionBusy
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerAction("previous")
              }
              Button {
                iconText: root.playerRunning && !root.playerPaused ? "\uf04c" : "\uf04b"
                tooltipText: root.playerRunning && !root.playerPaused ? "Pause" : "Play"
                enabled: !root.playerActionBusy
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerRunning ? root.playerAction("toggle") : root.playSelected()
              }
              Button {
                iconText: "\uf051"
                tooltipText: "Next station"
                enabled: root.playerRunning && !root.playerActionBusy
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerAction("next")
              }
              Button {
                iconText: "\uf04d"
                tooltipText: "Stop"
                enabled: (root.playerRunning || root.playPreparing)
                  && !stopProcess.running
                  && !root.playCancellationRequested
                  && (!playerActionProcess.running || root.playPreparing)
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.stopPlayer()
              }
            }

            Row {
              anchors.right: parent.right
              anchors.rightMargin: Style.spacing.md
              anchors.leftMargin: Style.spacing.sm
              anchors.bottom: parent.bottom
              anchors.bottomMargin: Style.spacing.sm
              spacing: Style.spacing.xs

              Button {
                anchors.verticalCenter: parent.verticalCenter
                iconText: root.playerMuted || root.playerVolume === 0 ? "\uf026" : "\uf028"
                tooltipText: root.playerMuted ? "Unmute" : "Mute (M)"
                active: root.playerMuted
                enabled: root.playerRunning && !root.playerActionBusy
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerAction("mute")
              }

              PanelSlider {
                id: volumeSlider
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(116)
                height: implicitHeight
                minimum: 0
                maximum: 100
                step: 1
                integer: true
                value: root.playerVolume
                trackColor: root.faint
                fillColor: root.accent
                knobColor: root.foreground
                tickColor: root.background
                enabled: !stopProcess.running
                Accessible.name: "Radio volume"
                onMoved: function(nextVolume) { root.setPlayerVolume(nextVolume) }
                onRightClicked: root.playerAction("mute")
              }

              Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(30)
                text: root.playerVolume + "%"
                textFormat: Text.PlainText
                color: root.dim
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
              }
            }
          }
        }
      }
    }
  }
}
