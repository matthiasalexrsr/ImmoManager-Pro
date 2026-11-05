"""Package native macOS/Linux builds; never cross-compile or relabel Windows files."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform not in {"darwin", "linux"}:
        parser.error("Build and package on a native macOS or Linux host.")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    arch = {"AMD64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if arch is None:
        parser.error("Unsupported native desktop architecture: " + platform.machine())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f"ImmoManager-Pro-{version}-{'macOS' if sys.platform == 'darwin' else 'Linux'}-{arch}"
    with tempfile.TemporaryDirectory(prefix="immo-package-") as temp:
        stage = Path(temp) / name
        stage.mkdir()
        shutil.copyfile(ROOT / "docs/DESKTOP_PLATFORMS.md", stage / "Plattformen-und-Start.md")
        (stage / "Demo-Start.txt").write_text(
            "ImmoManager Pro – vorbereitete Demo Baden-Württemberg\n\n"
            "Die Demo verwendet einen getrennten persönlichen Datenordner und synthetische Daten.\n"
            "Linux: Im Anwendungsordner Start-Demo-Desktop oder Start-Demo-Browser öffnen.\n"
            'macOS: open -a "ImmoManager Pro" --args --demo --mode standalone\n'
            'Browsermodus unter macOS: open -a "ImmoManager Pro" --args --demo --mode browser\n'
            "Eine bereits laufende Instanz zuerst geordnet beenden. Die normale Hauptanwendung\n"
            "öffnet weiterhin die eigenen Verwaltungsdaten.\n", encoding="utf-8")
        if sys.platform == "darwin":
            source = args.dist / "ImmoManager Pro.app"
            executable = source / "Contents/MacOS/ImmoManager-Pro"
            if not executable.is_file() or not (source / "Contents/Info.plist").is_file():
                raise RuntimeError("No genuine native macOS application bundle found")
            marker = source / "Contents/Resources/desktop-runtime.json"
            runtime = json.loads(marker.read_text(encoding="utf-8"))
            if runtime.get("workspaces") != ["own", "demo-bw"] or runtime.get("platform") != sys.platform:
                raise RuntimeError("The native application must include own-data and prepared-demo workspaces")
            shutil.copytree(source, stage / source.name, symlinks=True)
            (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
            destination = output / (name + ".dmg")
            if destination.exists():
                raise FileExistsError(destination)
            subprocess.run(["hdiutil", "create", "-volname", "ImmoManager Pro", "-srcfolder", str(stage),
                            "-format", "UDZO", str(destination)], check=True)
        else:
            source = args.dist / "ImmoManager-Pro"
            if not (source / "ImmoManager-Pro").is_file() or not (source / "ImmoManager-Pro-CLI").is_file():
                raise RuntimeError("No genuine native Linux application payload found")
            runtime = json.loads((source / "_internal/desktop-runtime.json").read_text(encoding="utf-8"))
            if runtime.get("workspaces") != ["own", "demo-bw"] or runtime.get("platform") != sys.platform:
                raise RuntimeError("The native application must include own-data and prepared-demo workspaces")
            shutil.copytree(source, stage / source.name, symlinks=True)
            for mode, title, demo in (("standalone", "Desktop", False), ("browser", "Browser", False),
                                      ("standalone", "Demo-Desktop", True), ("browser", "Demo-Browser", True)):
                launcher = stage / source.name / ("Start-" + title)
                launcher.write_text('#!/bin/sh\nset -eu\ncd -- "$(dirname -- "$0")"\n'
                                    f'exec ./ImmoManager-Pro {"--demo " if demo else ""}--mode {mode} "$@"\n', encoding="utf-8")
                launcher.chmod(0o755)
            destination = output / (name + ".tar.gz")
            if destination.exists():
                raise FileExistsError(destination)
            with tarfile.open(destination, mode="w:gz") as archive:
                archive.add(stage, arcname=name)
    with destination.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = {"version": version, "platform": sys.platform, "architecture": arch,
               "workspaces": runtime["workspaces"],
               "file": destination.name, "bytes": destination.stat().st_size, "sha256": checksum,
               "signed_or_notarized_by_this_script": False,
               "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    destination.with_suffix(destination.suffix + ".json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    destination.with_suffix(destination.suffix + ".sha256").write_text(checksum + "  " + destination.name + "\n", encoding="ascii")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
