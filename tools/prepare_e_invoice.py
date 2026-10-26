"""Fetch only the reviewed release assets and verify SHA-256 before extraction.

Build-time operation, never called by the application. No installation, registry
change or ambient Java is used. The resulting directory is an explicit package
input; its manifest also covers every extracted rule and runtime file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(target: Path) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    config = json.loads((Path(__file__).resolve().parents[1] / "backend/services/e_invoice/assets.json").read_text(encoding="utf-8"))
    for asset in config["assets"]:
        path = target / asset["filename"]
        if not path.exists() or sha(path) != asset["sha256"]:
            partial = path.with_suffix(path.suffix + ".part")
            request = urllib.request.Request(asset["url"], headers={"User-Agent": "ImmoManager-release-preparation"})
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            if sha(partial) != asset["sha256"]:
                raise RuntimeError("Release checksum mismatch: " + asset["name"])
            partial.replace(path)
        print(asset["name"] + " verified", flush=True)
        if "resource_directory" in asset:
            with ZipFile(path) as archive:
                for entry in archive.infolist():
                    if entry.is_dir() or not entry.filename.startswith(tuple(asset["resource_prefixes"])):
                        continue
                    out = target / asset["resource_directory"] / entry.filename
                    if not out.resolve().is_relative_to(target.resolve()) or ".." in PurePosixPath(entry.filename).parts:
                        raise RuntimeError("Unsafe resource path")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(archive.read(entry))
        if "extract" not in asset:
            continue
        destination = target / asset["extract"]
        destination.mkdir(exist_ok=True)
        with ZipFile(path) as archive:
            for entry in archive.infolist():
                pure = PurePosixPath(entry.filename)
                if pure.is_absolute() or ".." in pure.parts or "\\" in entry.filename or ":" in entry.filename:
                    raise RuntimeError("Unsafe release archive path")
                out = destination.joinpath(*pure.parts).resolve()
                if not out.is_relative_to(destination.resolve()):
                    raise RuntimeError("Release archive escapes destination")
                if entry.is_dir():
                    out.mkdir(parents=True, exist_ok=True)
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, out.open("wb") as stream:
                        shutil.copyfileobj(source, stream)
    manifest = {**config, "files": {p.relative_to(target).as_posix(): sha(p)
                for p in sorted(target.rglob("*")) if p.is_file() and p.name != "manifest.json"}}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    prepare(parser.parse_args().target.resolve())
