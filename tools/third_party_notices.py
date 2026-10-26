"""Collect unchanged third-party license/notice files for the explicitly chosen product."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_profile import document_tools, verify_wizard_assets  # noqa: E402


def requirements(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            yield from requirements(path.parent / line[3:].strip())
        elif not line.startswith("-"):
            yield Requirement(line)


def license_file(path):
    name = path.name.lower()
    return any(
        word in name for word in ("license", "licence", "copying", "copyright", "notice")
    ) and path.suffix.lower() not in (".py", ".pyc", ".js", ".map", ".ts")


def bundled_license(name, version):
    """Some npm tarballs omit their repository license; use only a verified exact release."""
    folder = ROOT / "packaging/third-party"
    for entry in json.loads((folder / "licenses.json").read_text(encoding="utf-8")):
        if entry["name"] != name or entry["version"] != version:
            continue
        if Path(entry["filename"]).name != entry["filename"]:
            raise RuntimeError("License source must be a plain filename")
        path = folder / entry["filename"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Upstream license checksum mismatch")
        return path, entry
    return None


def covered_sources(output):
    """Ship the exact pinned MPL source archive, checked against upstream's digest."""
    folder = ROOT / "packaging/third-party"
    entries = json.loads((folder / "sources.json").read_text(encoding="utf-8"))
    copied = []
    for entry in entries:
        filename = entry["filename"]
        if Path(filename).name != filename:
            raise RuntimeError("Source archive must be a plain filename")
        if metadata.version(entry["name"]) != entry["version"]:
            raise RuntimeError("Covered source version differs from the installed component")
        content = (folder / filename).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise RuntimeError("Covered source checksum mismatch")
        target = "source-" + filename
        (output / target).write_bytes(content)
        copied.append(target)
    (output / "sources.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return copied + ["sources.json"]


def generate(output=None):
    wizard_vendor, wizard_source = verify_wizard_assets(ROOT)
    output = Path(output or ROOT / "artifacts/THIRD_PARTY_NOTICES")
    output.mkdir(parents=True, exist_ok=True)
    rows, missing, excluded = [], [], []

    def record(ecosystem, name, version, expression, files):
        files = sorted({Path(file).resolve() for file in files if Path(file).is_file()})
        upstream = None
        if not files and ecosystem == "npm":
            fallback = bundled_license(name, version)
            if fallback:
                file, upstream = fallback
                files = [file]
                expression = upstream.get("license", expression)
        if not files:
            missing.append(f"{ecosystem}: {name}@{version}")
        identifier = re.sub(r"[^a-zA-Z0-9._-]", "_", f"{ecosystem}-{name}-{version}")
        sections = [f"{name} {version}\nDeclared license: {expression}\n"]
        if upstream:
            sections.append(f"Upstream license: {upstream['url']}\nSHA-256: {upstream['sha256']}\n")
        hashes = []
        for file in files:
            content = file.read_bytes()
            hashes.append({"name": file.name, "sha256": hashlib.sha256(content).hexdigest()})
            sections.append(f"\n----- {file.name} -----\n" + content.decode("utf-8", errors="replace"))
        (output / f"{identifier}.txt").write_text("\n".join(sections), encoding="utf-8")
        rows.append(
            {
                "ecosystem": ecosystem,
                "name": name,
                "version": version,
                "license": expression,
                "notice": f"{identifier}.txt",
                "sources": hashes,
            }
        )

    roots = list(requirements(ROOT / "requirements-runtime.txt"))
    # Desktop spec deliberately excludes the PostgreSQL driver.
    roots = [req for req in roots if canonicalize_name(req.name) != "psycopg2-binary"]
    if os.environ.get("IMMO_BUILD_BANK") == "1":
        roots += list(requirements(ROOT / "requirements-bank.txt"))
    if document_tools():
        roots += list(requirements(ROOT / "requirements-documents-optional.txt"))
    roots += [Requirement("PyInstaller")]
    seen = set()

    def visit(req):
        if req.marker and not req.marker.evaluate({"extra": ""}):
            return
        key = canonicalize_name(req.name)
        dist = metadata.distribution(req.name)
        if req.specifier and dist.version not in req.specifier:
            raise RuntimeError(f"Installed version mismatch: {req}, found {dist.version}")
        if key in seen:
            return
        seen.add(key)
        files = [dist.locate_file(file) for file in dist.files or [] if license_file(Path(str(file)))]
        record(
            "python",
            dist.metadata["Name"],
            dist.version,
            dist.metadata.get("License-Expression")
            or dist.metadata.get("License")
            or "; ".join(dist.metadata.get_all("Classifier", [])),
            files,
        )
        for dependency in dist.requires or []:
            visit(Requirement(dependency))

    for req in roots:
        visit(req)

    projects = [ROOT / "frontend"]
    if document_tools():
        projects.append(ROOT / "optional/document-editor")
    for project in projects:
        lock = json.loads((project / "package-lock.json").read_text(encoding="utf-8"))
        for relative, info in lock["packages"].items():
            if not relative or info.get("dev"):
                continue
            folder = project / relative
            if not folder.is_dir() and info.get("optional"):
                continue  # platform-specific binary for another OS, not shipped
            pkg = json.loads((folder / "package.json").read_text(encoding="utf-8"))
            if pkg["version"] != info["version"]:
                raise RuntimeError(f"npm lock mismatch: {relative}")
            # PDF.js' optional Node/Skia binaries are never part of its browser
            # worker or Vite assets; do not pretend their npm installation is shipped.
            if info.get("optional") and pkg["name"].startswith("@napi-rs/canvas-"):
                excluded.append(
                    {
                        "name": pkg["name"],
                        "version": pkg["version"],
                        "reason": "Node-only native canvas binary, absent from browser distribution",
                    }
                )
                continue
            files = []
            for parent, directories, names in os.walk(folder):
                directories[:] = [d for d in directories if d not in ("node_modules", ".git")]
                files.extend(Path(parent) / name for name in names if license_file(Path(name)))
            record("npm", pkg["name"], pkg["version"], pkg.get("license", info.get("license", "UNKNOWN")), files)

    record("runtime", "Python", sys.version.split()[0], "PSF-2.0", [Path(sys.base_prefix) / "LICENSE.txt"])
    record("asset", "Roboto-wizard", wizard_source["font_version"], "OFL-1.1",
           [wizard_vendor / "Roboto-OFL.txt", wizard_vendor / "SOURCES.json"])
    record("asset", "NotoSans", "bundled", "OFL-1.1", [ROOT / "backend/assets/fonts/OFL-Noto.txt"])
    record(
        "asset",
        "Tesseract-models",
        "bundled",
        "Apache-2.0",
        [ROOT / "backend/resources/tessdata/LICENSE", ROOT / "backend/resources/tessdata/SOURCES.json"],
    )
    record("application", "ImmoManager-Pro", "project", "MIT", [ROOT / "LICENSE"])
    (output / "inventory.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "not-distributed.json").write_text(json.dumps(excluded, indent=2), encoding="utf-8")
    (output / "README.txt").write_text(
        "Unchanged license and notice texts from the explicitly selected installed dependencies.\n"
        "Includes notices for build/runtime components where relevant to bundled code.\n"
        "This collection does not grant additional rights or replace source-distribution obligations.\n"
        "See docs/COMMERCIAL_RELEASE.md in the source distribution.\n",
        encoding="utf-8",
    )
    if missing:
        raise RuntimeError("Missing license texts (release blocked): " + ", ".join(missing))
    source_files = covered_sources(output)
    with (output / "README.txt").open("a", encoding="utf-8") as notice:
        notice.write(
            "\nCertifi is covered by MPL-2.0. Its complete, unchanged source archive is included\n"
            "as source-certifi-<version>.tar.gz alongside this notice, together with the MPL\n"
            "license text. You may obtain, modify and redistribute that source under MPL-2.0.\n"
            "Upstream URLs and SHA-256 digests are recorded in sources.json.\n"
        )
    # A previous optional-profile run must not leave misleading files in a core bundle.
    expected = (
        {row["notice"] for row in rows} | set(source_files) | {"inventory.json", "README.txt", "not-distributed.json"}
    )
    for path in output.iterdir():
        if path.is_file() and path.name not in expected:
            path.unlink()
    print(f"{len(rows)} components with license texts: {output}")
    return output


if __name__ == "__main__":
    generate()
