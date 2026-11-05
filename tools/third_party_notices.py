"""Collect unchanged third-party license/notice files for the explicitly chosen product."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import sysconfig
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


def tcl_tk_license_sources(versions):
    """Exact release texts; never guess a license when the bundled runtime changes."""
    folder = ROOT / "packaging/third-party"
    entries = json.loads((folder / "tcl-tk-licenses.json").read_text(encoding="utf-8"))
    result = []
    for name, version in versions.items():
        matches = [item for item in entries if item["name"] == name and item["version"] == version]
        if len(matches) != 1:
            raise RuntimeError(f"Missing exact Tcl/Tk license source: {name}@{version}")
        entry = matches[0]
        if Path(entry["filename"]).name != entry["filename"]:
            raise RuntimeError("Tcl/Tk license source must be a plain filename")
        path = folder / entry["filename"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Tcl/Tk license source checksum mismatch")
        result.append((name, version, entry["license"], path, entry))
    return result


def static_openssl_license_sources():
    """Bind the private macOS Intel static build to its exact original notices."""
    declared = os.environ.get("IMMO_STATIC_OPENSSL_PREFIX")
    if declared is None:
        return []
    if not declared or sys.platform != "darwin" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("The static OpenSSL source is only reviewed for native Intel macOS")
    prefix = Path(declared).resolve(strict=True)
    pinned = json.loads((ROOT / "packaging/third-party/openssl-static-macos.json").read_text(encoding="utf-8"))
    receipt_path = prefix / "build-receipt.json"
    if not receipt_path.resolve(strict=True).is_relative_to(prefix):
        raise RuntimeError("The static OpenSSL build receipt is outside its private prefix")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (pinned.get("schema") != "immomanager-static-openssl-source/1"
            or receipt.get("schema") != "immomanager-static-openssl-build/1"
            or any(receipt.get(key) != value for key, value in pinned.items() if key != "schema")
            or receipt.get("native_platform") != "darwin"
            or receipt.get("native_machine", "").lower() not in {"x86_64", "amd64"}
            or not receipt.get("openssl_version", "").startswith("OpenSSL " + pinned["version"] + " ")
            or receipt.get("compiler_environment", {}).get("MACOSX_DEPLOYMENT_TARGET") != pinned["deployment_target"]
            or "no-shared" not in receipt.get("configure_argv", [])
            or pinned["configure_target"] not in receipt.get("configure_argv", [])):
        raise RuntimeError("The static OpenSSL build differs from its exact reviewed source")
    files = receipt["files"]
    required = {"lib/libssl.a", "lib/libcrypto.a", "bin/openssl", "LICENSE.txt"}
    notices = {name for name in ("NOTICE", "NOTICE.txt") if (prefix / name).exists()}
    if set(files) != required | notices:
        raise RuntimeError("The static OpenSSL receipt omits or changes original notice files")
    for name, identity in files.items():
        path = (prefix / name).resolve(strict=True)
        if not path.is_relative_to(prefix) or path.stat().st_size != identity["bytes"]:
            raise RuntimeError("Changed static OpenSSL build or original notice")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != identity["sha256"]:
                raise RuntimeError("Changed static OpenSSL build or original notice")
    originals = [prefix / name for name in sorted({"LICENSE.txt"} | notices)]
    return [("OpenSSL (static cryptography linkage)", pinned["version"], "Apache-2.0",
             [*originals, receipt_path], {"url": pinned["source_url"], "sha256": pinned["source_sha256"]})]


def windows_tcl_tk_versions():
    """Read PE product versions without creating a Tk window or loading DLL code."""
    import tkinter

    from PyInstaller.utils.win32.versioninfo import read_version_info_from_executable

    versions = {}
    for name, major_minor in (("Tcl", tkinter.TclVersion), ("Tk", tkinter.TkVersion)):
        stem = name.lower() + str(major_minor).replace(".", "")
        candidates = [Path(sys.base_prefix) / "DLLs" / (stem + suffix) for suffix in ("t.dll", ".dll")]
        paths = [path for path in candidates if path.is_file()]
        if len(paths) != 1:
            raise RuntimeError(f"Cannot identify bundled {name} runtime DLL")
        info = read_version_info_from_executable(str(paths[0]))
        declared = {value.val for child in getattr(info, "kids", []) for table in getattr(child, "kids", [])
                    for value in getattr(table, "kids", []) if getattr(value, "name", None) == "ProductVersion"}
        if len(declared) != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", next(iter(declared))):
            raise RuntimeError(f"Cannot determine exact {name} runtime version")
        versions[name] = declared.pop()
    return versions


def python_license_sources(dist, output):
    """Some official Qt wheels omit texts; use their exact, verified full source."""
    files = [dist.locate_file(file) for file in dist.files or [] if license_file(Path(str(file)))]
    if files or canonicalize_name(dist.metadata["Name"]) not in {
        "pyside6", "shiboken6", "pyside6-essentials", "pyside6-addons"
    }:
        return files, None

    from tools.qt_sources import manifest

    sources = manifest()
    if dist.version != sources["version"]:
        raise RuntimeError(f"Missing exact Qt Python license source: {dist.metadata['Name']}@{dist.version}")
    upstream = next(row for row in sources["archives"] if row["module"] == "pyside-setup")
    folder = Path(output) / ("qt-" + dist.version)
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    if index.get("version") != dist.version or index.get("sources") != sources["archives"]:
        raise RuntimeError("Mismatched Qt Python license source inventory")
    for row in index["files"]:
        if row["archive"] != upstream["filename"]:
            continue
        relative = Path(row["file"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "pyside-setup":
            raise RuntimeError("Invalid Qt Python license source path")
        path = folder / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise RuntimeError("Changed Qt Python license source text")
        files.append(path)
    if not files:
        raise RuntimeError("Missing Qt Python original license texts")
    return files, upstream


def generate(output=None):
    wizard_vendor, wizard_source = verify_wizard_assets(ROOT)
    invoice_manifest = ROOT / "packaging/e-invoice-notices/manifest.json"
    hosting = os.environ.get('IMMO_PACKAGE_TARGET') == 'hosting'
    notice_inputs = invoice_manifest.read_bytes()
    if not hosting:
        notice_inputs += (ROOT / "packaging/third-party/qt-sources.json").read_bytes()
    notice_revision = hashlib.sha256(notice_inputs).hexdigest()[:12]
    output = Path(output or ROOT / ("artifacts/notices-" + notice_revision))
    output.mkdir(parents=True, exist_ok=True)
    desktop_rows = []
    if not hosting:
        from tools.qt_sources import notices as desktop_notices
        desktop_rows = desktop_notices(output)
    rows, missing, excluded = [], [], []

    def record(ecosystem, name, version, expression, files, upstream=None):
        files = sorted({Path(file).resolve() for file in files if Path(file).is_file()})
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
    # The desktop spec excludes PostgreSQL; the hosting image actually ships it.
    if not hosting:
        roots = [req for req in roots if canonicalize_name(req.name) != "psycopg2-binary"]
    if os.environ.get("IMMO_BUILD_BANK") == "1":
        roots += list(requirements(ROOT / "requirements-bank.txt"))
    if document_tools():
        roots += list(requirements(ROOT / "requirements-documents-optional.txt"))
    if not hosting:
        roots += [Requirement("PyInstaller")]
        roots += list(requirements(ROOT / "requirements-desktop.txt"))
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
        files, upstream = python_license_sources(dist, output)
        record(
            "python",
            dist.metadata["Name"],
            dist.version,
            dist.metadata.get("License-Expression")
            or dist.metadata.get("License")
            or "; ".join(dist.metadata.get_all("Classifier", [])),
            files,
            upstream=upstream,
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

    python_licenses = [Path(sys.base_prefix) / 'LICENSE.txt', Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
                       Path(sys.base_prefix) / 'LICENSE']
    record("runtime", "Python", sys.version.split()[0], "PSF-2.0", python_licenses)
    if not hosting and sys.platform == "win32":
        for name, version, expression, source, upstream in tcl_tk_license_sources(windows_tcl_tk_versions()):
            record("runtime", name, version, expression, [source], upstream=upstream)
    for name, version, expression, originals, upstream in static_openssl_license_sources():
        record("runtime", name, version, expression, originals, upstream=upstream)
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
    from tools.e_invoice_notices import catalog
    from tools.e_invoice_notices import generate as invoice_notices
    invoice_rows = invoice_notices(output)
    system_rows = []
    if hosting:
        from tools.hosting_notices import generate as system_notices
        system_rows = system_notices(output)
    catalog(output, [*rows, *invoice_rows, *desktop_rows, *system_rows])
    print(f"{len(rows) + len(invoice_rows) + len(desktop_rows) + len(system_rows)} components with license texts: {output}")
    return output


if __name__ == "__main__":
    generate()
