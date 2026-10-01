# Stopped playback controls

Real mpv comparison against main `7f2d119`, using four local stations. Each case
starts on the third station, reached with native Next twice.

| Action after Stop | Before | After |
| --- | --- | --- |
| `radio-player next` | First station playing | Fourth station playing |
| `radio-player previous` | Fourth station playing | Second station playing |
| MPRIS Next | First station playing | Fourth station playing |
| MPRIS Previous | Fourth station playing | Second station playing |
| Paused, then immediate Stop → Next | Fourth station paused | Fourth station playing |
| Paused, then immediate Stop → Previous | Second station paused | Second station playing |
| Bar right-click while externally stopped | Dispatches `stop` | Dispatches `toggle` |

The normal navigation cases run the production shell command or production
MPRIS service through private D-Bus, after mpv reports stopped. The immediate
cases send Pause, Stop, and navigation in one real mpv IPC batch. Their payload
comes from each version's production `radio-player`; shell startup is bypassed
to exercise event ordering directly.

Two mixed-version cases leave baseline Lua running while using the updated CLI.
Next still reaches the fourth station and Previous the second. This verifies
that a plugin update preserves active navigation before the player restarts.

The bar checks use Qt mouse clicks on the production widget and actual Omarchy
button. They verify the dispatched process command; process, filesystem, and
compositor IO are mocked. Playing and paused players still dispatch `stop`, and
an exited player still dispatches `resume`.

Audio comes from a localhost HTTP fixture and plays through mpv's null output.
Each run uses separate temporary XDG directories; MPRIS uses a private D-Bus
session. No host audio, saved stations, or desktop configuration is used.

[evidence.json](evidence.json) records native status, stream requests, transport
boundaries, Qt results, mpv version, and hashes of the candidate files tested.
All six candidate navigation cases and both mixed-version cases passed.
