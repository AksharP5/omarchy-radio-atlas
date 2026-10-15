import fs from "node:fs"
import path from "node:path"

export function linkShellUi(directory, shellDirectory) {
  const shell = path.resolve(shellDirectory)
  const qs = path.join(directory, "qs")
  const commons = path.join(qs, "Commons")
  fs.mkdirSync(commons, { recursive: true })
  fs.symlinkSync(path.join(shell, "Ui"), path.join(qs, "Ui"))
  for (const name of fs.readdirSync(path.join(shell, "Commons"))) {
    if (name === "qmldir") continue
    fs.symlinkSync(path.join(shell, "Commons", name), path.join(commons, name))
  }
  // Keep real styles without registering unrelated shell service singletons.
  fs.writeFileSync(path.join(commons, "qmldir"), "module qs.Commons\n"
    + ["Border", "Color", "Style", "Util"]
      .map(name => `singleton ${name} 1.0 ${name}.qml\n`).join(""))
}
