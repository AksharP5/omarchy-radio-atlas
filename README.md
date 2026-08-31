# Radio Atlas

Explore live radio on a rotatable globe from the Omarchy bar. Click a station
signal to play it, or click a country to browse its stations. Playback runs in
Omarchy's existing `mpv` and `mpv-mpris` setup, so `omarchy.media` provides the
usual play, pause, previous, and next controls.

[View Radio Atlas on the Omarchy Plugin Marketplace](https://omarchyplugins.com/plugin.html?id=akshar.radio-atlas)

![Radio Atlas showing live stations across the globe](preview.png)

## Features

- Kinetic drag rotation that highlights a nearby station when it settles, plus deep wheel zoom on a theme-aware globe
- A fast cached world view that progressively adds thousands of stations and keeps the session catalog when closed
- Country stations stay on the session globe and take priority over background signals
- Country-level map estimates when a station has no published coordinates
- Automatic country focus for the station that is actually playing
- Current station identity, track metadata, and one-click favoriting in the player
- Instant cached results while full-directory search and country browsing refresh from Radio Browser
- Random tuning that avoids recent stations, plus favorites and listening history
- Independent volume slider, mute, and bar-wheel volume control
- Audio output picker that routes radio to any PipeWire sink, including AirPlay speakers exposed as RAOP sinks
- Click-through desktop focus outside the atlas panel
- Automatic dismissal when Omarchy starts its screensaver
- Keyboard navigation
- Persistent world and country caches with background refresh and transient retries
- Automatic skip to the next playlist entry when a stream fails

## Install

```bash
omarchy plugin add https://github.com/AksharP5/omarchy-radio-atlas.git --enable
```

Radio Atlas uses `bubblewrap`, `curl`, `iproute2`, `jq`, `mpv`, `python`,
`socat`, `coreutils`, and `util-linux`. These packages ship with Omarchy.
`mpv-mpris` connects playback to `omarchy.media` and is also part of the
standard Omarchy installation.

## Remove

Stop the independent radio player before removing the plugin:

```bash
~/.config/omarchy/plugins/akshar.radio-atlas/radio-player stop
omarchy plugin remove akshar.radio-atlas
```

Favorites, listening history, volume, and the selected audio output remain in
`~/.local/share/radio-atlas/state.json` so reinstalling restores them. Remove
`~/.local/share/radio-atlas/` manually if you also want to delete that data.

## Controls

| Input | Action |
| --- | --- |
| Drag or flick globe | Rotate; a flick coasts and highlights a nearby station |
| Wheel over globe | Zoom |
| Click signal | Play station |
| Click country | Browse country |
| `/` | Focus search |
| Up / Down | Move through stations |
| Enter | Play selected station |
| Space | Play or pause |
| `R` | Tune a random station |
| `F` | Favorite selected station |
| `+` / `-` | Raise or lower radio volume |
| `M` | Mute or unmute |
| Speaker icon | Choose the audio output |
| `?` | Show or hide controls |
| Escape | Hide controls, clear search, or close |

On the bar, left click opens Radio Atlas, middle click tunes randomly, right
click stops its player, and the mouse wheel adjusts radio volume.

## Audio outputs and AirPlay

The speaker button next to the volume slider chooses where radio plays. It lists
every PipeWire output device through `pactl`, which ships with Omarchy's
PipeWire setup. "System default" follows the desktop's current output, the
choice is saved alongside the volume in `~/.local/share/radio-atlas/state.json`,
and switching while playing takes effect immediately. If the chosen device
disappears, mpv may pause and will not always resume when it returns. Choose
"System default" or another available output, then resume playback.

AirPlay speakers appear in this list once PipeWire exposes them as RAOP sinks.
On Arch Linux, the RAOP modules ship in the optional `pipewire-zeroconf`
package. Install it, enable discovery, and restart the user services:

```bash
sudo pacman -S pipewire-zeroconf
mkdir -p ~/.config/pipewire/pipewire.conf.d
cp /usr/share/pipewire/pipewire.conf.avail/50-raop.conf \
  ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire wireplumber
```

If you run a firewall such as ufw, allow the timing feedback AirPlay speakers
send back to the sender on UDP ports 6001-6002; without it the session connects
but the speaker stays silent:

```bash
sudo ufw allow in from 192.168.0.0/16 to any port 6001:6002 proto udp
```

PipeWire's RAOP discovery occasionally drops a sink when a device briefly
stops announcing itself over mDNS. If an AirPlay speaker disappears from the
output list, re-discover it with `systemctl --user restart pipewire wireplumber`.

PipeWire's RAOP sink streams classic AirPlay audio as uncompressed PCM.
AirPort Express, Apple TV, many AV receivers, and HomePods accept it; AirPlay 2
only features such as HomePod stereo pairs are not supported. A device that
refuses the stream simply stays silent; pick another output to recover.

## Data and privacy

Station data comes from the community-run
[Radio Browser](https://www.radio-browser.info/). Radio Atlas sends its name
and version as the HTTP user agent. Starting a station calls Radio Browser's
click-count endpoint. Favorites and history stay in
`~/.local/share/radio-atlas/state.json`.

Station metadata and stream URLs are community supplied. Labels are rendered
as plain text. Playback runs in an isolated network namespace and reaches
stations through a bounded proxy that rejects private and effectively local
destinations, including after redirects. Remote metadata and local JSON are
size- and record-limited before they reach the shell. Radio Atlas still connects
directly to third-party stations; HTTP streams are unencrypted. Only play
stations you trust.

Map geometry comes from public-domain Natural Earth data.

## Troubleshooting

Player and proxy diagnostics are written to
`$XDG_RUNTIME_DIR/omarchy-radio-atlas/mpv.log` and `proxy.log`. If saved state
is malformed, oversized, or contains too many entries, Radio Atlas refuses to
overwrite it and reports
`~/.local/share/radio-atlas/state.json`; back up that file before repairing or
removing it.

## Development

```bash
./tests/run
qmllint -I /usr/share/omarchy/shell BarWidget.qml Globe.qml RadioAtlas.qml
```
