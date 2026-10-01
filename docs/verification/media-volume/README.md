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

The native check covers the live volume, saved state, and a restarted player.
The focused MPRIS tests also cover rejected mpv updates and invalid saved state.
