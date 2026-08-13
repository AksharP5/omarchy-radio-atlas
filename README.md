# Radio Atlas

Explore live radio on a rotatable globe from the Omarchy bar. Click a station
signal to play it, or click a country to browse its stations. Playback runs in
Omarchy's existing `mpv` and `mpv-mpris` setup, so `omarchy.media` provides the
usual play, pause, previous, and next controls.

## Features

- Drag, momentum, and wheel zoom on a theme-aware globe
- Station and country selection directly on the map
- Search by station, country, or genre
- Random tuning, favorites, and recent stations
- Independent volume slider, mute, and bar-wheel volume control
- Keyboard navigation
- Radio Browser mirror fallback and a 30-minute world cache
- Automatic skip to the next playlist entry when a stream fails

## Install

```bash
omarchy plugin add https://github.com/AksharP5/omarchy-radio-atlas.git --enable
```

The repository is private during local development. Clone it through an
authenticated GitHub session or link the checkout into
`~/.config/omarchy/plugins/akshar.radio-atlas`.

## Controls

| Input | Action |
| --- | --- |
| Drag globe | Rotate |
| Wheel over globe | Zoom |
| Click signal | Select station |
| Click country | Browse country |
| `/` | Focus search |
| Up / Down | Move through stations |
| Enter | Play selected station |
| Space | Play or pause |
| `R` | Tune a random station |
| `F` | Favorite selected station |
| `+` / `-` | Raise or lower radio volume |
| `M` | Mute or unmute |
| Escape | Clear search or close |

On the bar, left click opens Radio Atlas, middle click tunes randomly, right
click stops its player, and the mouse wheel adjusts radio volume.

## Data and privacy

Station data comes from the community-run
[Radio Browser](https://www.radio-browser.info/). Radio Atlas sends its name
and version as the HTTP user agent. Starting a station calls Radio Browser's
click-count endpoint. Favorites and history stay in
`~/.local/share/radio-atlas/state.json`.

Map geometry comes from public-domain Natural Earth data.

## Development

```bash
./tests/run
qmllint -I /usr/share/omarchy/shell BarWidget.qml Globe.qml RadioAtlas.qml
```
