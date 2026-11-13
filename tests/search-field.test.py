"""Run the production search field against a lazy native Qt clipboard offer."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


PROJECT = Path(__file__).resolve().parents[1]
SHELL = Path(os.environ.get("OMARCHY_SHELL_DIR", "/usr/share/omarchy/shell"))

with tempfile.TemporaryDirectory(prefix="radio-atlas-search-field-") as temporary:
    root = Path(temporary)
    commons = root / "qs/Commons"
    commons.mkdir(parents=True)
    (root / "qs/Ui").symlink_to(SHELL / "Ui", target_is_directory=True)
    for source in (SHELL / "Commons").iterdir():
        if source.name != "qmldir":
            (commons / source.name).symlink_to(source)
    (commons / "qmldir").write_text("module qs.Commons\n" + "".join(
        f"singleton {name} 1.0 {name}.qml\n" for name in ("Border", "Color", "Style", "Util")))
    shutil.copytree(PROJECT / "tests/qml-imports/Quickshell", root / "Quickshell")
    (root / "SearchField.qml").symlink_to(PROJECT / "SearchField.qml")
    # The subprocess boundary is exercised separately by clipboard.test.py.
    (root / "RadioProcess.qml").write_text("""import QtQuick
Item {
  property var command: []
  property bool running: false
  property QtObject stdout
  signal exited(int exitCode, int exitStatus)
}
""")
    fixture = root / "search.qml"
    fixture.write_text("""import QtQuick
Item {
  width: 350; height: 80
  SearchField { objectName: "field"; width: 300; height: implicitHeight }
  Item { x: 320; width: 10; height: 10; activeFocusOnTab: true }
}
""")
    flags = subprocess.check_output(["pkg-config", "--cflags", "--libs",
                                     "Qt6Quick", "Qt6Test"], text=True)
    binary = root / "clipboard-native"
    subprocess.run(["g++", "-std=c++17", "-fPIC", str(PROJECT / "tests/clipboard-native.cpp"),
                    "-o", str(binary), *shlex.split(flags)], check=True)
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_NO_XDG_DESKTOP_PORTAL="1", QT_QPA_PLATFORMTHEME="")
    control = subprocess.run([str(binary), str(fixture), "--native-paste-control"],
                             env=environment, timeout=15)
    if control.returncode != 90:
        raise RuntimeError(f"Native clipboard control exited {control.returncode}, expected 90")
    subprocess.run([str(binary), str(fixture)], env=environment, check=True, timeout=15)
print("Native clipboard ownership, bounded paste, editing, and IME tests passed")
