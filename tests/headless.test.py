"""Run the suite on a private bus and reject desktop portal activation."""
import os
from pathlib import Path
import shlex
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
  <listen>unix:tmpdir=/tmp</listen>
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

    # Verify the activation detector before trusting a zero-request result.
    control = subprocess.run(bus + ['dbus-send', '--session', '--print-reply',
                             '--dest=org.freedesktop.portal.Desktop',
                             '/org/freedesktop/portal/desktop', 'org.freedesktop.DBus.Peer.Ping'],
                             env=environment, capture_output=True, text=True, timeout=10)
    assert marker.exists() and marker.read_text().splitlines() == ['portal requested'], \
        f'Fake portal activation detector failed:\n{control.stderr}'
    marker.unlink()

    command = sys.argv[1:] or ['./tests/run']
    result = subprocess.run(bus + command, cwd=project, env=environment, timeout=240)
    assert result.returncode == 0, f'Headless tests exited with {result.returncode}'
    requests = marker.read_text().splitlines() if marker.exists() else []
    assert not requests, f'Headless tests attempted {len(requests)} desktop portal activations'

print('Headless tests passed; desktop portal activation attempts: 0')
