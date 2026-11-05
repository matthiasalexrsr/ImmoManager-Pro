"""Pinned release selection and safe ZIP/tar readers, shared by build and runtime."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import posixpath
import stat
import sysconfig
import tarfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from ..filesystem_paths import filesystem_path

SUPPORTED_PLATFORMS = ("windows-x64", "linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64")


def platform_id() -> str:
    system, machine = platform.system().lower(), platform.machine().lower()
    architecture = {"amd64": "x64", "x86_64": "x64", "x64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system == "windows":
        # On Windows ARM the x64 application may run under OS emulation. Select
        # the application's Python architecture, never pretend a native ARM JRE
        # exists in the pinned Temurin release (it does not).
        compiled = sysconfig.get_platform().lower()
        if compiled == "win-amd64":
            architecture = "x64"
        elif compiled in ("win-arm64", "win32"):
            raise ValueError("The reviewed Windows invoice runtime requires the x64 application; no native ARM64 JRE is published for this pin")
    selected = system + "-" + str(architecture)
    if selected not in SUPPORTED_PLATFORMS:
        raise ValueError("No reviewed invoice runtime is available for this operating system and architecture")
    return selected


def configuration(path: Path | None = None, target_platform: str | None = None) -> dict:
    value = json.loads((path or Path(__file__).with_name('assets.json')).read_text(encoding='utf-8'))
    selected = target_platform or platform_id()
    if selected not in SUPPORTED_PLATFORMS:
        raise ValueError('Unsupported invoice runtime platform')
    assets = [asset for asset in value['assets'] if asset.get('platform', selected) == selected]
    if sum(asset.get('extract') == 'runtime' for asset in assets) != 1:
        raise ValueError('Exactly one reviewed runtime is required')
    result = {'format': value['format'], 'platform': selected, 'assets': assets}
    if selected.startswith("darwin-"):
        # Keep original Mach-O bytes inside a pinned archive while the outer
        # application is signed. Materialize and verify privately before use.
        result['runtime_mode'] = 'archive-cache'
    return result


def file_sha(path: Path) -> str:
    with filesystem_path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime_legal_files(root: Path, manifest: dict):
    """Publish the actual pinned runtime legal bytes, even for deferred macOS JREs."""
    for asset in manifest['assets']:
        if asset.get('extract') != 'runtime':
            continue
        archive = root / safe_name(asset['filename'])
        if file_sha(archive) != asset['sha256']:
            raise ValueError('Runtime archive checksum mismatch')
        for name, content, _ in extracted(asset, archive):
            if name.startswith('runtime/') and '/legal/' in name:
                yield name.removeprefix('runtime/'), content, hashlib.sha256(content).hexdigest()


def safe_name(name: str) -> str:
    pure = PurePosixPath(name)
    if not name or pure.as_posix() == '.' or pure.is_absolute() or '..' in pure.parts or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('Unsafe archive member path')
    return pure.as_posix()


def extracted(asset: dict, archive_path: Path):
    """Yield (relative path, unchanged bytes, executable flag); no filesystem writes.

    Runtime legal symlinks in Temurin tar archives are materialized as regular
    files from an archive-internal target. No host path or live symlink is read.
    """
    resource = asset.get('resource_directory')
    destination = asset.get('extract')
    if resource:
        with ZipFile(archive_path) as archive:
            seen = set()
            for member in archive.infolist():
                if member.is_dir() or not member.filename.startswith(tuple(asset['resource_prefixes'])):
                    continue
                name = safe_name(resource + '/' + safe_name(member.filename))
                if name in seen or stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError('Ambiguous archive resource')
                seen.add(name)
                yield name, archive.read(member), False
    if not destination:
        return
    safe_name(destination)
    if archive_path.name.endswith('.zip'):
        with ZipFile(archive_path) as archive:
            seen = set()
            for member in archive.infolist():
                name = safe_name(destination + '/' + safe_name(member.filename))
                if member.is_dir():
                    continue
                if name in seen or stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError('Ambiguous archive member')
                seen.add(name)
                yield name, archive.read(member), bool(member.external_attr >> 16 & 0o111)
    elif archive_path.name.endswith('.tar.gz'):
        with tarfile.open(archive_path, 'r:gz') as tar_archive:
            members = tar_archive.getmembers()
            index = {safe_name(member.name): member for member in members}
            if len(index) != len(members):
                raise ValueError('Duplicate tar member')

            def content(member, chain=()):
                if member.name in chain or len(chain) > 16:
                    raise ValueError('Cyclic archive link')
                if member.issym() or member.islnk():
                    if PurePosixPath(member.linkname).is_absolute() or '\\' in member.linkname or ':' in member.linkname:
                        raise ValueError('Unsafe archive link')
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname)
                                                if member.issym() else member.linkname)
                    safe_name(target)
                    if target not in index:
                        raise ValueError('Missing archive link target')
                    return content(index[target], (*chain, member.name))
                if not member.isfile():
                    raise ValueError('Special archive member')
                stream = tar_archive.extractfile(member)
                if stream is None:
                    raise ValueError('Unreadable archive member')
                with stream:
                    return stream.read(), bool(member.mode & 0o111)

            for tar_member in members:
                if not tar_member.isdir():
                    raw, executable = content(tar_member)
                    yield destination + '/' + safe_name(tar_member.name), raw, executable
    else:
        raise ValueError('Unreviewed archive format')


def verify(root: Path, expected: dict | None = None, *, materialized: bool = False) -> tuple[dict, str]:
    root = filesystem_path(root.resolve())
    expected = expected or configuration()
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if any(manifest.get(key) != expected[key] for key in ('format', 'platform', 'assets')):
        raise ValueError('Unreviewed invoice assets or platform')
    if manifest.get('runtime_mode', 'bundled') != expected.get('runtime_mode', 'bundled'):
        raise ValueError('Unreviewed invoice runtime transport mode')
    if bool(manifest.get('runtime_materialized', False)) != materialized:
        raise ValueError('Unreviewed materialized runtime state')
    deferred = expected.get('runtime_mode') == 'archive-cache'
    if materialized and not deferred:
        raise ValueError('Only archive-cache runtimes have a materialized state')
    files = {}
    for asset in expected['assets']:
        name = safe_name(asset['filename'])
        path = root / name
        if file_sha(path) != asset['sha256']:
            raise ValueError('Release checksum mismatch')
        files[name] = asset['sha256']
        if deferred and not materialized and asset.get('extract') == 'runtime':
            continue
        for member, content, _executable in extracted(asset, path):
            if member in files:
                raise ValueError('Duplicate extracted file')
            files[member] = hashlib.sha256(content).hexdigest()
            if materialized and _executable and os.name != 'nt' and not (root / member).stat().st_mode & 0o111:
                raise ValueError('A materialized runtime executable is not executable')
    present = set()
    for path in root.rglob('*'):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Bundle links are forbidden')
        if path.is_file() and path != root / 'manifest.json':
            name = path.relative_to(root).as_posix()
            present.add(name)
            if name not in files or file_sha(path) != files[name]:
                raise ValueError('Extracted bundle checksum mismatch')
    if files != manifest['files'] or present != set(files):
        raise ValueError('Incomplete bundle inventory')
    return manifest, hashlib.sha256(raw).hexdigest()
