# Audio output recovery

Verified on mpv 0.41.0, PipeWire 1.6.9, and WirePlumber 0.5.17.
Each test creates private audio services and a private D-Bus session, using
synthetic sinks and a generated tone. The desktop's audio services, devices,
and settings are not changed.

[WirePlumber's default policy](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/settings.html#linking-pause-playback)
pauses players through MPRIS when their sink disappears. With mpv-mpris 1.3,
main reproduced the original silence after reconnection. The original PR also
overrode a deliberate MPRIS pause when an unrelated output appeared.

Radio Atlas now owns its MPRIS receiver. It identifies the sender of Pause
through D-Bus credentials and `/proc`, so WirePlumber's policy pause can be
distinguished from a human pause, including a second Pause while already paused.
Only an automatic pause interrupting active playback on a named PipeWire output
arms recovery. That same output must be present for one guarded resume attempt.
Device lists may coalesce rapid removal and return; recovery does not depend on
seeing an absent snapshot or on the order of pause and device notifications.

| Version and scenario | Observed result |
| --- | --- |
| Main `bbe41e5`: selected output returns | Stayed paused; playback did not advance |
| Original PR `f23917c`: MPRIS pause, unrelated output appears | Unexpectedly resumed |
| Fixed: selected output returns, three cycles | Unpaused, position advanced, routed to selected sink, nonzero PCM |
| Fixed: three rapid disconnect/reconnect cycles | Playback and nonzero PCM returned to selected sink |
| Fixed: unrelated output appears while selected output is missing | Stayed paused |
| Fixed: already paused through UI or MPRIS, then output changes | Stayed paused |
| Fixed: another human MPRIS Pause while automatically paused | Stayed paused after reconnect |
| Fixed: human Pause immediately before removal | Stayed paused after reconnect |
| Fixed: UI toggle cancels recovery | Stayed paused after reconnect |
| Fixed: repeated Stop followed by Play or PlayPause | Restarted the same station at playlist index 1 with nonzero PCM |

All eight real audio tests passed in 27.174 seconds. Both negative controls
failed for the reproduced bugs. Thirteen focused tests cover event ordering,
coalesced device lists, output flapping, cancellation, resume guards, normal
media controls, metadata, volume, and WirePlumber executable replacement. The full suite and QML lint also passed.
[Recorded states and PCM peaks](evidence.jsonl) include baseline, original PR,
and fixed results. Peak samples from the returned output exceed 7,000 on the
signed 16-bit scale, alongside advancing playback and an uncorked stream routed
to that output. This checks audio, rather than just the pause property.

An earlier timing-based revision missed rapid reconnects and could confuse a
manual pause with an automatic one. Those review findings prompted the single
MPRIS owner and are covered by the current tests. System default is intentionally
not tracked: it does not name the output to wait for. It still needs manual
resume after a device-loss pause.

Run the focused and full checks:

```bash
python3 tests/mpris.test.py
dbus-run-session -- ./tests/run
python3 tests/audio-output.test.py --require-dependencies --artifacts /tmp/radio-atlas-audio-proof
```

CI installs the audio tools and runs the real audio tests with required
dependencies; a missing dependency fails the job. Local runs without
`--require-dependencies` skip when the audio tools are unavailable.
To repeat the negative controls, extract the old Lua scripts and run:

```bash
git show bbe41e5:radio-status.lua > /tmp/radio-atlas-main.lua
git show f23917c:radio-status.lua > /tmp/radio-atlas-original.lua
python3 tests/audio-output.test.py --legacy-player --script /tmp/radio-atlas-main.lua --scenario reconnect
python3 tests/audio-output.test.py --legacy-player --script /tmp/radio-atlas-original.lua --scenario mpris-pause
```

Legacy controls additionally require `/usr/lib/mpv-mpris/mpris.so`. The fixed
player and CI use the bundled MPRIS receiver instead.
