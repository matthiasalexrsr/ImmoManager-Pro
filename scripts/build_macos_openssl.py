"""Build pinned, independent OpenSSL for the Intel macOS cryptography extension.

Never substitute a Homebrew bottle whose object files may target a newer macOS.
This build uses the original hash-pinned LTS source and an explicit macOS 13
deployment target, entirely inside a new private CI build directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packaging/third-party/openssl-static-macos.json"


def file_identity(path: Path) -> dict:
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_archive(path: Path, pinned: dict) -> None:
    if file_identity(path) != {"bytes": pinned["source_bytes"], "sha256": pinned["source_sha256"]}:
        raise RuntimeError("The OpenSSL source archive does not match its pinned size and SHA-256")


def extract_source(archive: Path, destination: Path, version: str) -> Path:
    expected_root = "openssl-" + version
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not parts or parts[0] != expected_root or ".." in parts or "\\" in member.name
                    or not (member.isdir() or member.isfile())):
                raise RuntimeError("Unsafe member in the pinned OpenSSL archive: " + member.name)
        # Members were validated in full before creating a single extracted file.
        for member in members:
            path = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            original = source.extractfile(member)
            if original is None:
                raise RuntimeError("Cannot read the original OpenSSL source file: " + member.name)
            with original, path.open("xb") as target:
                shutil.copyfileobj(original, target)
            path.chmod(member.mode & 0o755)
    return destination / expected_root


def build(output: Path) -> dict:
    if sys.platform != "darwin" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("The static OpenSSL source build requires a native Intel macOS host")
    pinned = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    archive = output / ("openssl-" + pinned["version"] + ".tar.gz")
    request = urllib.request.Request(pinned["source_url"], headers={"User-Agent": "ImmoManager-native-build"})
    with urllib.request.urlopen(request, timeout=120) as response, archive.open("xb") as target:
        shutil.copyfileobj(response, target)
    verify_archive(archive, pinned)
    source = extract_source(archive, output / "source", pinned["version"])
    prefix = output / "install"
    environment = os.environ.copy()
    environment.update({"MACOSX_DEPLOYMENT_TARGET": pinned["deployment_target"], "CC": "/usr/bin/clang",
                        "CFLAGS": "-O2 -fPIC -mmacosx-version-min=" + pinned["deployment_target"],
                        "LDFLAGS": "-mmacosx-version-min=" + pinned["deployment_target"]})
    configure = ["/usr/bin/perl", str(source / "Configure"), pinned["configure_target"],
                 "no-shared", "no-module", "no-tests", "--prefix=" + str(prefix),
                 "--openssldir=" + str(prefix / "ssl"), "--libdir=lib"]
    with (output / "compiler.log").open("w", encoding="utf-8") as log:
        for command in (configure, ["/usr/bin/make", "-j" + str(min(8, os.cpu_count() or 2)), "build_sw"],
                        ["/usr/bin/make", "install_sw"]):
            log.write(json.dumps(command) + "\n")
            log.flush()
            subprocess.run(command, cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=1200)
    shutil.copyfile(source / "LICENSE.txt", prefix / "LICENSE.txt")
    notice_names = [name for name in ("NOTICE", "NOTICE.txt") if (source / name).is_file()]
    for name in notice_names:
        shutil.copyfile(source / name, prefix / name)
    if list(prefix.rglob("*.dylib")):
        raise RuntimeError("The independent OpenSSL build unexpectedly created dynamic libraries")
    version = subprocess.run([str(prefix / "bin/openssl"), "version", "-a"], capture_output=True,
                             text=True, check=True, timeout=30).stdout
    if not version.startswith("OpenSSL " + pinned["version"] + " "):
        raise RuntimeError("The independent OpenSSL binary reports an unexpected source version")
    files = {name: file_identity(prefix / name) for name in
             ("lib/libssl.a", "lib/libcrypto.a", "bin/openssl", "LICENSE.txt", *notice_names)}
    receipt = {**pinned, "schema": "immomanager-static-openssl-build/1", "native_platform": sys.platform,
               "native_machine": platform.machine(), "configure_argv": configure,
               "compiler_environment": {key: environment[key] for key in
                                        ("CC", "CFLAGS", "LDFLAGS", "MACOSX_DEPLOYMENT_TARGET")},
               "openssl_version": version, "files": files}
    (prefix / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = build(args.output)
    print(json.dumps(receipt), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
