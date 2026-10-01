"""Run the suite on a private bus and reject desktop portal activation."""
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

project = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix='radio-atlas-headless-') as temporary:
    directory = Path(temporary)
    services = directory / 'services'
    services.mkdir()
    marker = directory / 'portal-requests'
    fake = directory / 'fake-portal'
    fake.write_text('''#!/bin/sh
printf 'portal requested\n' >> "$RADIO_ATLAS_TEST_PORTAL_MARKER"
exit 1
''')
    (services / 'org.freedesktop.portal.Desktop.service').write_text(
        '[D-BUS Service]\nName=org.freedesktop.portal.Desktop\n'
        f'Exec=/bin/sh {shlex.quote(str(fake))}\n')
    config = directory / 'bus.conf'
    config.write_text(f'''<busconfig>
  <type>session</type>
  <listen>unix:tmpdir={escape(str(directory))}</listen>
  <auth>EXTERNAL</auth>
  <servicedir>{escape(str(services))}</servicedir>
  <policy context="default">
    <allow own="*"/>
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
  </policy>
</busconfig>
''')
    environment = {**os.environ, 'RADIO_ATLAS_TEST_PORTAL_MARKER': str(marker),
                   'XDG_CURRENT_DESKTOP': 'Hyprland', 'QT_QPA_PLATFORMTHEME': 'gtk3',
                   'QT_NO_XDG_DESKTOP_PORTAL': '0'}
    bus = ['dbus-run-session', '--config-file', str(config), '--']

    def run_on_bus(command, *, timeout, capture_output=False):
        process = subprocess.Popen(bus + command, cwd=project, env=environment,
                                   start_new_session=True, text=True,
                                   stdout=subprocess.PIPE if capture_output else None,
                                   stderr=subprocess.PIPE if capture_output else None)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        finally:
            # The private bus and command share this owned process group.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    # Verify the activation detector before trusting a zero-request result.
    control = run_on_bus(['dbus-send', '--session', '--print-reply',
                             '--dest=org.freedesktop.portal.Desktop',
                             '/org/freedesktop/portal/desktop', 'org.freedesktop.DBus.Peer.Ping'],
                             capture_output=True, timeout=10)
    if not marker.exists() or marker.read_text().splitlines() != ['portal requested']:
        raise RuntimeError(f'Fake portal activation detector failed:\n{control.stderr}')
    marker.unlink()

    command = sys.argv[1:] or ['./tests/run']
    result = run_on_bus(command, timeout=240)
    if result.returncode != 0:
        raise RuntimeError(f'Headless tests exited with {result.returncode}')
    requests = marker.read_text().splitlines() if marker.exists() else []
    if requests:
        raise RuntimeError(f'Headless tests attempted {len(requests)} desktop portal activations')

print('Headless tests passed; desktop portal activation attempts: 0')
