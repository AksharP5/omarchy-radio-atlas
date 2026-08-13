import QtQuick
import QtQuick.Controls as QQC
import Quickshell
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

  property bool fetching: false
  property string fetchAction: ""
  property string pendingFetchAction: ""
  property string pendingFetchValue: ""
  property string fetchError: ""
  property string fetchOutput: ""
  property string fetchStderr: ""

  property bool playerRunning: false
  property bool playerPaused: false
  property bool playerMuted: false
  property int playerVolume: 70
  property int pendingVolume: 70
  property string playerTitle: ""
  property int playlistPosition: -1
  property int playlistCount: 0

  readonly property string fetchPath: Qt.resolvedUrl("radio-fetch").toString().replace(/^file:\/\//, "")
  readonly property string playerPath: Qt.resolvedUrl("radio-player").toString().replace(/^file:\/\//, "")
  readonly property string statePath: Qt.resolvedUrl("radio-state").toString().replace(/^file:\/\//, "")

  readonly property var displayStations: mode === "favorites"
    ? favorites
    : (mode === "recent" ? recent : results)
  readonly property var currentGeoStations: {
    var current = RadioModel.mergeGeoStations([], displayStations)
    return current.length > 0 ? current : worldStations
  }
  readonly property bool lightTheme:
    0.2126 * background.r + 0.7152 * background.g + 0.0722 * background.b > 0.5

  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property color scrim: Color.menu.scrim
  property color accent: Color.accent
  property color urgent: Color.urgent
  property color dim: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.56)
  property color faint: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.12)
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
    refreshPlayerStatus()
    if (payload.action === "random") tuneRandom()
    else if (worldStations.length === 0) showWorld()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    opened = false
  }

  function dismiss() {
    opened = false
    if (shell && typeof shell.hide === "function")
      shell.hide((manifest && manifest.id) || "akshar.radio-atlas")
  }

  function setSelection(index) {
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
    if (selectedIndex < 0) setSelection(delta < 0 ? displayStations.length - 1 : 0)
    else setSelection((selectedIndex + delta + displayStations.length) % displayStations.length)
  }

  function setStationList(nextMode, stations) {
    mode = nextMode
    if (nextMode !== "favorites" && nextMode !== "recent") results = stations
    setSelection(stations.length > 0 ? 0 : -1)
  }

  function startFetch(action, value) {
    if (fetchProcess.running) {
      pendingFetchAction = action
      pendingFetchValue = value || ""
      fetching = true
      return
    }
    fetching = true
    fetchAction = action
    fetchError = ""
    fetchOutput = ""
    fetchStderr = ""
    fetchProcess.command = value ? [fetchPath, action, value] : [fetchPath, action]
    fetchProcess.running = true
  }

  function showWorld() {
    activeCountryCode = ""
    activeCountryName = ""
    startFetch("world", "")
  }

  function showFavorites() {
    mode = "favorites"
    activeCountryCode = ""
    activeCountryName = ""
    setSelection(favorites.length > 0 ? 0 : -1)
  }

  function showRecent() {
    mode = "recent"
    activeCountryCode = ""
    activeCountryName = ""
    setSelection(recent.length > 0 ? 0 : -1)
  }

  function search(text) {
    var query = String(text || "").trim()
    if (!query) {
      showWorld()
      return
    }
    activeCountryCode = ""
    activeCountryName = ""
    startFetch("search", query)
    keyCatcher.forceActiveFocus()
  }

  function browseCountry(code, name) {
    activeCountryCode = code
    activeCountryName = name
    searchField.text = name
    startFetch("country", code)
    keyCatcher.forceActiveFocus()
  }

  function tuneRandom() {
    activeCountryCode = ""
    activeCountryName = ""
    startFetch("random", "")
  }

  function activateMapStation(station) {
    var index = RadioModel.indexByUuid(displayStations, station.uuid)
    if (index < 0) return
    setSelection(index)
    playSelected()
  }

  function playlistScope() {
    if (mode === "favorites") return "favorites"
    if (mode === "recent") return "recent"
    return "results"
  }

  function playSelected() {
    if (!selectedStation || playerActionProcess.running) return
    playerActionProcess.action = "play"
    playerActionProcess.output = ""
    playerActionProcess.command = [playerPath, "play", selectedStation.uuid, playlistScope()]
    playerActionProcess.running = true
    recordPlayed(selectedStation.uuid)
  }

  function playerAction(action) {
    if (playerActionProcess.running) return
    playerActionProcess.action = action
    playerActionProcess.output = ""
    playerActionProcess.command = [playerPath, action]
    playerActionProcess.running = true
  }

  function applyPlayerState(raw) {
    try {
      var state = JSON.parse(raw || "{}")
      playerRunning = state.running === true
      playerPaused = state.paused === true
      playerMuted = state.muted === true
      playerVolume = Math.round(Number(state.volume === undefined ? 70 : state.volume))
      playerTitle = String(state.title || "")
      playlistPosition = Number(state.playlistPosition === undefined ? -1 : state.playlistPosition)
      playlistCount = Number(state.playlistCount || 0)

      if (playerTitle) {
        for (var i = 0; i < displayStations.length; i++) {
          if (displayStations[i].name === playerTitle) {
            selectedIndex = i
            selectedStation = displayStations[i]
            break
          }
        }
      }
    } catch (error) {
      playerRunning = false
      playerPaused = false
      playerMuted = false
      playerTitle = ""
    }
  }

  function refreshPlayerStatus() {
    if (!playerStatusProcess.running && !playerActionProcess.running)
      playerStatusProcess.running = true
  }

  function setPlayerVolume(value) {
    pendingVolume = Math.max(0, Math.min(100, Math.round(value)))
    playerVolume = pendingVolume
    volumeTimer.restart()
  }

  function changePlayerVolume(delta) {
    setPlayerVolume(playerVolume + delta)
  }

  function loadState() {
    if (stateProcess.running) return
    stateProcess.action = "get"
    stateProcess.output = ""
    stateProcess.command = [statePath, "get"]
    stateProcess.running = true
  }

  function applyLocalState(raw) {
    try {
      var state = JSON.parse(raw || "{}")
      favorites = Array.isArray(state.favorites) ? state.favorites : []
      recent = Array.isArray(state.recent) ? state.recent : []
    } catch (error) {
      favorites = []
      recent = []
    }
  }

  function isFavorite(uuid) {
    return RadioModel.indexByUuid(favorites, uuid) >= 0
  }

  function toggleFavorite(uuid) {
    if (!uuid || stateProcess.running) return
    stateProcess.action = "favorite"
    stateProcess.output = ""
    stateProcess.command = [statePath, "favorite", uuid]
    stateProcess.running = true
  }

  function recordPlayed(uuid) {
    if (!uuid || historyProcess.running) return
    historyProcess.output = ""
    historyProcess.command = [statePath, "played", uuid]
    historyProcess.running = true
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
      if (root.pendingFetchAction) {
        var nextAction = root.pendingFetchAction
        var nextValue = root.pendingFetchValue
        root.pendingFetchAction = ""
        root.pendingFetchValue = ""
        root.fetching = false
        Qt.callLater(function() { root.startFetch(nextAction, nextValue) })
        return
      }

      root.fetching = false
      if (exitCode !== 0) {
        root.fetchError = String(root.fetchStderr || "Station service is unavailable").trim()
        return
      }

      var stations = []
      try { stations = JSON.parse(root.fetchOutput || "[]") } catch (error) {
        root.fetchError = "Station data was not valid"
        return
      }
      if (!Array.isArray(stations)) stations = []

      if (root.fetchAction === "world") {
        root.worldStations = stations
        root.setStationList("world", stations)
      } else if (root.fetchAction === "country") {
        root.setStationList("country", stations)
      } else if (root.fetchAction === "search") {
        root.setStationList("search", stations)
      } else if (root.fetchAction === "random") {
        root.setStationList("random", stations)
        if (stations.length > 0) root.playSelected()
      }

      if (stations.length === 0) root.fetchError = "No working stations found"
    }
  }

  Process {
    id: volumeProcess
    property string output: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: volumeProcess.output = text
    }
    onExited: root.applyPlayerState(output)
  }

  Process {
    id: playerActionProcess
    property string action: ""
    property string output: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: playerActionProcess.output = text
    }
    onExited: {
      root.applyPlayerState(output)
      root.loadState()
    }
  }

  Process {
    id: playerStatusProcess
    property string output: ""
    command: [root.playerPath, "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: playerStatusProcess.output = text
    }
    onExited: root.applyPlayerState(output)
  }

  Process {
    id: stateProcess
    property string action: ""
    property string output: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: stateProcess.output = text
    }
    onExited: {
      root.applyLocalState(output)
      if (root.mode === "favorites") root.setSelection(root.favorites.length > 0 ? Math.min(root.selectedIndex, root.favorites.length - 1) : -1)
    }
  }

  Process {
    id: historyProcess
    property string output: ""
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: historyProcess.output = text
    }
    onExited: root.applyLocalState(output)
  }

  Timer {
    interval: root.playerRunning ? 1800 : 5000
    repeat: true
    running: root.opened
    triggeredOnStart: true
    onTriggered: root.refreshPlayerStatus()
  }

  Timer {
    id: volumeTimer
    interval: 90
    repeat: false
    onTriggered: {
      if (volumeProcess.running) {
        restart()
        return
      }
      volumeProcess.output = ""
      volumeProcess.command = [root.playerPath, "volume", String(root.pendingVolume)]
      volumeProcess.running = true
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-radio-atlas"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      anchors.centerIn: parent
      color: root.background
      borderSpec: Border.surfaceSpec("menu", "border", root.border, Math.max(1, Style.normalBorderWidth))
      radius: Style.cornerRadius

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true
        z: 1

        Keys.priority: Keys.AfterItem
        Keys.onPressed: function(event) {
          if (searchField.activeFocus) {
            if (event.key === Qt.Key_Escape) {
              if (searchField.text) searchField.clear()
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
          color: root.foreground
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        Rectangle {
          anchors.left: title.right
          anchors.leftMargin: Style.spacing.md
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(6)
          height: width
          radius: width / 2
          color: root.fetching ? root.dim : (root.fetchError ? root.urgent : root.accent)
        }

        TextField {
          id: searchField
          anchors.right: randomButton.left
          anchors.rightMargin: Style.spacing.sm
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(Style.space(330), card.width * 0.32)
          placeholderText: "Search station, country, or genre"
          foreground: root.foreground
          accent: root.accent
          enabled: !root.fetching
          onAccepted: root.search(text)
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
            selectedStation: root.selectedStation
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
            onInteractionStarted: keyCatcher.forceActiveFocus()
            onStationActivated: function(station) { root.activateMapStation(station) }
            onCountryActivated: function(code, name) { root.browseCountry(code, name) }
          }

          Text {
            anchors.left: parent.left
            anchors.leftMargin: Style.spacing.panelPadding
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.spacing.md
            text: root.activeCountryName
              ? root.activeCountryName + "  ·  click another country to retune"
              : "Drag to rotate  ·  wheel to zoom  ·  click a signal or country"
            color: root.dim
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            anchors.right: parent.right
            anchors.rightMargin: Style.spacing.panelPadding
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.spacing.md
            text: root.currentGeoStations.length + " signals"
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
              color: root.selectedIndex === index
                ? Style.selectedFillFor(root.foreground, root.accent)
                : (rowMouse.containsMouse ? Style.hoverFillFor(root.foreground, root.accent) : "transparent")

              Accessible.name: modelData.name + ", " + RadioModel.stationMeta(modelData)
              Accessible.role: Accessible.ListItem
              Accessible.selected: root.selectedIndex === index

              Rectangle {
                visible: root.playerTitle === stationRow.modelData.name
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 2
                color: root.accent
              }

              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.spacing.md
                anchors.right: favoriteButton.left
                anchors.rightMargin: Style.spacing.sm
                anchors.top: parent.top
                anchors.topMargin: Style.space(10)
                text: stationRow.modelData.name
                color: root.foreground
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.body
                font.bold: root.playerTitle === stationRow.modelData.name
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
                active: root.isFavorite(stationRow.modelData.uuid)
                foreground: root.foreground
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
              visible: !root.fetching && root.displayStations.length === 0
              text: root.mode === "favorites"
                ? "No favorites yet. Select a station and press F."
                : (root.mode === "recent" ? "No listening history yet." : root.fetchError)
              color: root.dim
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.Wrap
            }

            Text {
              anchors.centerIn: parent
              visible: root.fetching
              text: "LOADING STATIONS"
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
              anchors.right: parent.right
              anchors.rightMargin: Style.spacing.md
              anchors.top: parent.top
              anchors.topMargin: Style.spacing.md
              text: root.playerRunning ? root.playerTitle : "Nothing playing"
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
              text: !root.playerRunning
                ? "Choose a signal to begin"
                : (root.playerPaused ? "Paused" : "Live")
                  + (root.playlistCount > 1 ? "  ·  " + root.playlistCount + " stations queued" : "")
              color: root.dim
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
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
                enabled: root.playerRunning
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerAction("previous")
              }
              Button {
                iconText: root.playerRunning && !root.playerPaused ? "\uf04c" : "\uf04b"
                tooltipText: root.playerRunning && !root.playerPaused ? "Pause" : "Play"
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerRunning ? root.playerAction("toggle") : root.playSelected()
              }
              Button {
                iconText: "\uf051"
                tooltipText: "Next station"
                enabled: root.playerRunning
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerAction("next")
              }
              Button {
                iconText: "\uf04d"
                tooltipText: "Stop"
                enabled: root.playerRunning
                focusable: true
                foreground: root.foreground
                accent: root.accent
                onClicked: root.playerAction("stop")
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
                Accessible.name: "Radio volume"
                onMoved: function(nextVolume) { root.setPlayerVolume(nextVolume) }
                onRightClicked: root.playerAction("mute")
              }

              Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(30)
                text: root.playerVolume + "%"
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
