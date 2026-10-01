# System media volume persistence

Changing Radio Atlas volume from 40% to 20% through MPRIS used to leave 40%
in saved state, so the next player session returned to 40%. The fixed bridge
saves 20%, and the next player session plays at 20%.

[evidence.json](evidence.json) records both runs against real mpv and the Radio
Atlas MPRIS bridge. The baseline uses commit
`311dbda74b2d698be31bfad31aeb0cb091473ed7`. The regression test runs on a private
D-Bus and PipeWire stack with a synthetic sink and a generated tone. It does not
use the desktop's audio services, hardware, or public streams.

Run the same check with:

```sh
python3 tests/audio-output.test.py --scenario volume --require-dependencies
```

The native check covers live volume, saved state, and startup through
`radio-player play`. Its mpv wrapper replaces only the network playlist with a
local tone, keeping the real session, sandbox, MPRIS bridge, and startup flags.

A second native check holds the saved-state lock, verifies Pause still responds
within half a second, and overlaps MPRIS and UI volume changes. Both live volume
and saved volume end at the UI's 40%. The bridge processes its own requests in
order and uses the existing CLI lock to coordinate with the UI.

Focused MPRIS tests cover integer rounding, numeric validation, preservation of
other state fields, and save errors. The existing CLI checks cover rejected mpv
updates. Stopping the bridge during a blocked request also terminated its worker
without changing saved state.
