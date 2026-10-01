# Headless test portal activation

The headless Radio Atlas suite started a temporary Hyprland desktop portal on
its private D-Bus session. That process crashed while exiting after the tests
passed. This patch prevents the tests from activating the portal.

The reproduction used a private bus whose only activatable service was a fake
`org.freedesktop.portal.Desktop`. Its executable recorded each activation and
exited. Real desktop services were never launched during this reproduction.

The unmodified native keyboard test passed in every experiment, but portal
activation depended on its environment:

| Qt settings | Portal activation attempts |
| --- | ---: |
| Inherited GTK theme, portal probe enabled | 2 |
| Inherited GTK theme, `QT_NO_XDG_DESKTOP_PORTAL=1` | 2 |
| Empty platform theme, portal probe enabled | 0 |
| Empty platform theme, `QT_NO_XDG_DESKTOP_PORTAL=1` | 0 |

Clearing the GTK platform theme eliminated the observed activation requests.
The Qt flag also disables the automatic desktop-services portal probe in
[Qt's source](https://github.com/qt/qtbase/blob/6.10/src/gui/platform/unix/qdesktopunixservices.cpp#L376-L389).

After the patch, the full `tests/run` suite passed on the same private bus with
zero portal activation attempts. The parent environment explicitly supplied
`QT_QPA_PLATFORMTHEME=gtk3`, `QT_NO_XDG_DESKTOP_PORTAL=0`, and
`XDG_CURRENT_DESKTOP=Hyprland`, so the result tests the overrides in each native
Qt invocation rather than relying on a sanitized parent shell.

[evidence.json](evidence.json) records the outcomes, Qt version, tested entry
points, and hashes of the validated test files. No UI behavior changes here.

Repeat the check from the repository root:

```bash
python3 tests/headless.test.py
```

The checker creates and removes its own bus configuration and fake portal
service. It first requests the fake service and verifies that the activation
marker was written. It then starts a fresh private bus, runs the full suite with
the inherited GTK settings above, and rejects any portal activation attempt.
CI runs this checker too. Real desktop service directories are excluded.

The checker also rejected the unmodified keyboard test from the base commit,
reporting two activation attempts even though its QML assertions passed.

Terminal SIGINT, SIGTERM, and external-timeout checks left no test command,
detached child, private bus process, or socket behind. Native cleanup handlers
finished. The checker keeps the suite in the foreground and relies on CI's
existing job timeout. Its socket lives in an owned short directory under `/tmp`,
so a long caller `TMPDIR` does not exceed the Unix socket-path limit.
The checker also rejected a failed command and the unmodified keyboard test
with Python optimization enabled; the fixed keyboard test still passed.
