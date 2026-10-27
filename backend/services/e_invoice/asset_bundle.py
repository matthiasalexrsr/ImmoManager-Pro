"""Pinned release selection and safe ZIP/tar readers, shared by build and runtime."""
from __future__ import annotations

import hashlib
import json
import platform
import posixpath
import stat
import tarfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from ..filesystem_paths import filesystem_path


def platform_id() -> str:
    system, machine = platform.system().lower(), platform.machine().lower()
    if system not in ('windows', 'linux') or machine not in ('amd64', 'x86_64'):
        raise ValueError('The reviewed invoice runtime supports Windows/Linux x64 only')
    return system + '-x64'


def configuration(path: Path | None = None, target_platform: str | None = None) -> dict:
    value = json.loads((path or Path(__file__).with_name('assets.json')).read_text(encoding='utf-8'))
    selected = target_platform or platform_id()
    if selected not in ('windows-x64', 'linux-x64'):
        raise ValueError('Unsupported invoice runtime platform')
    assets = [asset for asset in value['assets'] if asset.get('platform', selected) == selected]
    if sum(asset.get('extract') == 'runtime' for asset in assets) != 1:
        raise ValueError('Exactly one reviewed runtime is required')
    return {'format': value['format'], 'platform': selected, 'assets': assets}


def file_sha(path: Path) -> str:
    with filesystem_path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


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


def verify(root: Path, expected: dict | None = None) -> tuple[dict, str]:
    root = filesystem_path(root.resolve())
    expected = expected or configuration()
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if any(manifest.get(key) != expected[key] for key in ('format', 'platform', 'assets')):
        raise ValueError('Unreviewed invoice assets or platform')
    files = {}
    for asset in expected['assets']:
        name = safe_name(asset['filename'])
        path = root / name
        if file_sha(path) != asset['sha256']:
            raise ValueError('Release checksum mismatch')
        files[name] = asset['sha256']
        for member, content, _executable in extracted(asset, path):
            if member in files:
                raise ValueError('Duplicate extracted file')
            files[member] = hashlib.sha256(content).hexdigest()
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
