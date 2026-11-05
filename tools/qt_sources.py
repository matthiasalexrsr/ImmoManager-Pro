"""Prepare pinned Qt source archives and original upstream license notices.

Source archives are release sidecars, not duplicated inside the application.
No archive member is extracted to an archive-controlled filesystem path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packaging/third-party/qt-sources.json"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema") != "immomanager-qt-sources/1" or data.get("version") != "6.11.3":
        raise RuntimeError("Unreviewed desktop engine sources")
    for row in data["archives"]:
        if Path(row["filename"]).name != row["filename"] or len(row["sha256"]) != 64:
            raise RuntimeError("Invalid desktop source identity")
        if not row["url"].startswith("https://download.qt.io/official_releases/"):
            raise RuntimeError("Desktop sources must come from the reviewed upstream")
    return data


def fetch(row, cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / row["filename"]
    if target.exists():
        if target.is_symlink() or digest(target) != row["sha256"]:
            raise RuntimeError("Changed Qt source archive: " + row["filename"])
        return target
    partial = target.with_suffix(target.suffix + ".partial")
    if partial.exists():
        raise RuntimeError("Incomplete concurrent Qt source preparation: " + str(partial))
    try:
        with urllib.request.urlopen(row["url"], timeout=120) as source, partial.open("xb") as out:
            shutil.copyfileobj(source, out, length=1024 * 1024)
        if digest(partial) != row["sha256"]:
            raise RuntimeError("Qt upstream source checksum mismatch: " + row["filename"])
        partial.rename(target)
    finally:
        if partial.is_file():
            partial.unlink()
    return target


def is_notice(name):
    path = PurePosixPath(name)
    base = path.name.casefold()
    return ((base.startswith(("license", "licence", "copying", "copyright", "notice"))
             or any(part.casefold() in {"licenses", "licences"} for part in path.parts[:-1]))
            and path.suffix.casefold() not in {".c", ".cc", ".cpp", ".h", ".py", ".js", ".png", ".jpg", ".qrc"}
            or base == "qt_attribution.json")


def prepare(cache=None):
    data = manifest()
    cache = Path(cache or ROOT / "artifacts/qt-sources")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda row: fetch(row, cache), data["archives"]))
    return cache


def notices(output):
    data = manifest()
    cache = prepare()
    revision = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:12]
    prepared = ROOT / "artifacts" / ("qt-notices-" + revision)
    index_path = prepared / "index.json"
    if not index_path.is_file():
        prepared.mkdir(parents=True, exist_ok=True)
        rows = []
        for entry in data["archives"]:
            folder = prepared / entry["module"]
            folder.mkdir(exist_ok=True)
            count = 0
            with tarfile.open(cache / entry["filename"], mode="r|xz") as archive:
                for member in archive:
                    if not member.isfile() or not is_notice(member.name):
                        continue
                    if member.size > 32 * 1024 * 1024:
                        raise RuntimeError("Unexpectedly large Qt notice: " + member.name)
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise RuntimeError("Unreadable Qt notice: " + member.name)
                    content = stream.read()
                    checksum = hashlib.sha256(content).hexdigest()
                    # A bounded flat name also avoids Windows MAX_PATH on Chromium's tree.
                    name = checksum[:20] + ".txt"
                    (folder / name).write_bytes(content)
                    rows.append({"archive": entry["filename"], "original_path": member.name,
                                 "file": entry["module"] + "/" + name,
                                 "bytes": len(content), "sha256": checksum})
                    count += 1
            if not count:
                raise RuntimeError("Missing Qt upstream notices: " + entry["module"])
        index_path.write_text(json.dumps({"schema": "immomanager-qt-notices/1", "version": data["version"],
                                          "sources": data["archives"], "files": rows}, indent=2) + "\n", encoding="utf-8")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index["sources"] != data["archives"]:
        raise RuntimeError("Stale Qt notice preparation")
    for row in index["files"]:
        path = prepared / row["file"]
        if path.is_symlink() or digest(path) != row["sha256"]:
            raise RuntimeError("Changed Qt upstream notice")
    target = Path(output) / "qt-6.11.3"
    shutil.copytree(prepared, target, dirs_exist_ok=True)
    instructions = (
        "Qt / PySide6 6.11.3 are dynamically linked, unmodified upstream libraries.\n"
        "Their original licenses and third-party notices are indexed in index.json.\n"
        "The complete pinned upstream source archives are provided as release sidecars\n"
        "in the Qt-Quellen folder alongside this installer/download package. The same\n"
        "sources, SHA-256 digests and upstream URLs are recorded in index.json.\n"
        "The Qt libraries can be replaced with compatible modified versions in the\n"
        "application's _internal/PySide6 directory; keep ABI, architecture and resource\n"
        "layout compatible. No check forbids debugging such library modifications.\n"
        "PySide build instructions: https://doc.qt.io/qtforpython-6/building_from_source/index.html\n"
        "Qt build instructions: https://doc.qt.io/qt-6/build-sources.html\n"
        "The ImmoManager source and PyInstaller spec are distributed in the project\n"
        "repository; the source commit is recorded in the package acceptance receipt.\n"
    )
    (target / "README.txt").write_text(instructions, encoding="utf-8")
    return [{"ecosystem": "runtime", "name": "Qt / PySide6 / Chromium", "version": data["version"],
             "license": "LGPL-3.0 and upstream component licenses; see original texts", "notice": "qt-6.11.3/README.txt"}]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    print(prepare(args.cache))
