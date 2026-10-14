import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const source = fs.readFileSync(new URL("../RadioAtlas.qml", import.meta.url), "utf8")
const imports = source.match(/^import qs\.Commons(?: as \w+)?$/gm)
const colors = source.match(/^  property color (?:background|foreground|border|accent|urgent):.*$/gm)
const lightTheme = source.match(/^  readonly property bool lightTheme:\n[^\n]+/m)?.[0]
assert.ok(imports, "Could not find the production Commons imports")
assert.equal(colors?.length, 5, "Could not find the five production palette bindings")
assert.ok(lightTheme, "Could not find the production light-theme binding")

const shellDirectory = process.env.OMARCHY_SHELL_DIR || "/usr/share/omarchy/shell"
assert.ok(fs.existsSync(path.join(shellDirectory, "Commons/Color.qml")),
  "Set OMARCHY_SHELL_DIR to an Omarchy checkout's shell directory")
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "radio-atlas-theme-palette-"))

try {
  // Keep the real palette and its dependencies, excluding unrelated shell services.
  const commons = path.join(directory, "qs/Commons")
  fs.mkdirSync(commons, { recursive: true })
  for (const name of ["Color.qml", "Util.qml", "BorderGeometry.js"])
    fs.copyFileSync(path.join(shellDirectory, "Commons", name), path.join(commons, name))
  fs.writeFileSync(path.join(commons, "qmldir"),
    "module qs.Commons\nsingleton Color 1.0 Color.qml\nsingleton Util 1.0 Util.qml\n")
  fs.cpSync(fileURLToPath(new URL("./qml-imports/Quickshell", import.meta.url)),
    path.join(directory, "Quickshell"), { recursive: true })
  fs.writeFileSync(path.join(directory, "tst_theme_palette.qml"), `
import QtQuick
import QtTest
${imports.join("\n")}
import qs.Commons as ThemePalette

TestCase {
  id: root
  name: "ThemePalette"
${colors.join("\n")}
${lightTheme}

  function test_liveThemeSwitch() {
    var themes = [
      { background: "#172839", foreground: "#e1e2e3", border: "#456789",
        accent: "#aabbcc", urgent: "#ee1122", light: false },
      { background: "#eeddcc", foreground: "#123456", border: "#987654",
        accent: "#345678", urgent: "#900001", light: true }
    ]
    for (var i = 0; i < themes.length; i++) {
      var theme = themes[i]
      ThemePalette.Color.background = "#334455"
      ThemePalette.Color.foreground = "#ababab"
      ThemePalette.Color.accent = theme.accent
      ThemePalette.Color.urgent = theme.urgent
      ThemePalette.Color.shellValues = ({
        "menu.background": theme.background,
        "menu.text": theme.foreground,
        "menu.border": theme.border
      })
      compare(root.background, Qt.color(theme.background))
      compare(root.foreground, Qt.color(theme.foreground))
      compare(root.border, Qt.color(theme.border))
      compare(root.accent, Qt.color(theme.accent))
      compare(root.urgent, Qt.color(theme.urgent))
      compare(root.lightTheme, theme.light)
    }
  }
}
`)
  const result = spawnSync("/usr/lib/qt6/bin/qmltestrunner",
    ["-platform", "offscreen", "-import", directory, "-input", directory], {
      env: { ...process.env, QT_QUICK_BACKEND: "software",
        QT_NO_XDG_DESKTOP_PORTAL: "1", QT_QPA_PLATFORMTHEME: "" },
      stdio: "inherit",
    })
  if (result.error) throw result.error
  assert.equal(result.status, 0, "Theme palette tests failed")
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
