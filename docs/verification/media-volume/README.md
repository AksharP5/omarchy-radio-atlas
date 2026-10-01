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
within half a second, and submits MPRIS 20%, MPRIS 30%, then UI 40% before
releasing the lock. Both live volume and saved volume end at the UI's 40%.
The bridge keeps one active worker and the latest pending media level. It holds
the shared player lock across that burst, so UI writes cannot interleave with
the live updates and saves. Writers follow lock ownership, rather than global
request-arrival order.

The focused command above runs all four volume checks. The third sends consecutive
20% and 80% requests, then 200 changes at 60 requests per second while holding the
state lock for 5.5 seconds. All requests succeed, and live and saved volume end at
the last requested 99%. The fourth stops the bridge with one active and one
pending volume change. Both requests fail, the shared lock is released, and the
original saved 40% remains intact.

Focused MPRIS tests cover integer rounding, numeric validation, preservation of
other state fields, save errors, and coalescing while a UI writer owns the lock.
The CLI checks cover rejected mpv updates and missing inherited locks.
