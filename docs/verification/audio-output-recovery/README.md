# Audio output recovery

Verified on mpv 0.41.0, mpv-mpris 1.3, PipeWire 1.6.9, and WirePlumber 0.5.17.
Each test creates private audio services and a private D-Bus session, using
synthetic sinks and a generated tone. The desktop's audio services, devices,
and settings are not changed.

[WirePlumber's default policy](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/settings.html#linking-pause-playback)
pauses players through MPRIS when their sink disappears. Without mpv-mpris,
the same sink-removal reproduction kept playing. Enabling mpv-mpris reproduced
the original silence after reconnection.

| Version and scenario | Observed result |
| --- | --- |
| Main `bbe41e5`: selected output returns | Still paused; position stayed at 1.176750 seconds |
| Original PR `f23917c`: MPRIS pause, unrelated output appears | Unexpectedly resumed; position advanced from 0.327061 to 0.841752 seconds |
| Fixed: selected output returns, three cycles | Unpaused, position advanced, routed to the selected sink, captured nonzero PCM |
| Fixed: unrelated output appears while selected output is missing | Stayed paused |
| Fixed: already paused through UI or MPRIS, then output changes | Stayed paused |
| Fixed: UI toggle cancels armed recovery | Stayed paused after reconnection |

The final uninstrumented run passed all four integration tests. Both negative
controls failed for the reproduced bugs. The Lua regression tests, full suite,
and QML lint also passed. [Recorded states and PCM peaks](evidence.jsonl) show
the baseline, original PR, and final patch.

Recovery intentionally requires an observable removal followed promptly by a
pause. One earlier run missed a reconnect recovery without a trace explaining
why. Subsequent diagnostic runs covered both callback orders and two bounded
12-cycle reconnect runs, including a capture with no added property reads or
callback IO. The final production script passed. Ambiguous events still require
manual resume; the implementation does not infer device loss from every pause.
System default is not tracked, and a repeated MPRIS Pause while already paused
cannot cancel recovery. Stop cancels it.

Run the deterministic checks:

```bash
lua tests/audio-recovery.test.lua radio-status.lua
./tests/run
```

Run the optional real audio checks on an Omarchy host with the existing audio
tools and `/usr/lib/mpv-mpris/mpris.so` available:

```bash
python3 tests/audio-output.test.py --artifacts /tmp/radio-atlas-audio-proof
```

The harness skips when its dependencies are unavailable. Compare an old Lua
script using `--script PATH --scenario reconnect` or `--scenario mpris-pause`.
