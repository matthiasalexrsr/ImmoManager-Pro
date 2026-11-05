"""Materialize the pinned macOS JRE outside the signed application bundle.

Only bundled, hash-verified archives are read. No download, shell command,
application database or shared temporary runtime is used. Every cache reuse is
checked against the original archives rather than trusting a rewritten cache
manifest to approve altered executable bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

from .asset_bundle import configuration, extracted, file_sha, safe_name, verify

_PREPARATION_LOCK = threading.Lock()


def _link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _default_cache_base() -> Path:
    from ...config import settings
    from ...platform_paths import default_user_data_dir

    # Direct source/server callers without DATA_DIR still get a personal cache,
    # never backend.paths' historical source-tree fallback.
    data = Path(settings.data_dir).expanduser().resolve() if settings.data_dir else default_user_data_dir().resolve()
    return data / "resource-cache" / "e-invoice"


def _private_cache_base(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts or _link(path) or _link(path.parent):
        raise ValueError("The invoice cache must be a direct absolute private directory")
    base = path.resolve()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        if base.stat().st_uid != getattr(os, "getuid")():
            raise ValueError("The invoice cache belongs to another user")
        base.chmod(0o700)
    return base


def _existing(target: Path, expected: dict) -> tuple[dict, str] | None:
    if _link(target):
        raise ValueError("Runtime cache links are forbidden")
    if not target.exists():
        return None
    return verify(target, expected, materialized=True)


def materialize_runtime_bundle(root: Path, expected: dict | None = None, *, cache_dir: Path | None = None) -> tuple[Path, dict, str]:
    """Return a verified execution bundle, keeping ordinary platforms unchanged."""
    expected = configuration() if expected is None else expected
    root = root.resolve()
    package, package_digest = verify(root, expected)
    if expected.get("runtime_mode") != "archive-cache":
        return root, package, package_digest
    base = _private_cache_base(_default_cache_base() if cache_dir is None else cache_dir)
    target = base / package_digest
    with _PREPARATION_LOCK:
        try:
            current = _existing(target, expected)
        except (OSError, ValueError):
            # Do not follow or remove an injected link. An ordinary corrupted
            # cache is preserved under a new name, never recursively deleted.
            if _link(target) or target.resolve().parent != base:
                raise ValueError("Unsafe invoice runtime cache") from None
            try:
                target.rename(base / (".invalid-" + package_digest + "-" + uuid4().hex))
            except FileNotFoundError:
                pass  # another process already quarantined the same cache
            current = None
        if current is not None:
            return target, *current
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=base) as temporary:
            staging = Path(temporary)
            files = dict(package["files"])
            for name in files:
                relative = safe_name(name)
                source, destination = root / relative, staging / relative
                if _link(source):
                    raise ValueError("Source bundle links are forbidden")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination, follow_symlinks=False)
                if file_sha(destination) != files[name]:
                    raise ValueError("Source bundle changed during cache preparation")
            for asset in expected["assets"]:
                if asset.get("extract") != "runtime":
                    continue
                archive = staging / safe_name(asset["filename"])
                if file_sha(archive) != asset["sha256"]:
                    raise ValueError("Runtime archive checksum mismatch")
                for name, content, executable in extracted(asset, archive):
                    name = safe_name(name)
                    if name in files:
                        raise ValueError("Duplicate runtime cache file")
                    destination = staging / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                    if os.name != "nt":
                        destination.chmod(0o755 if executable else 0o644)
                    files[name] = hashlib.sha256(content).hexdigest()
            manifest = {**expected, "runtime_materialized": True, "files": files}
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            verify(staging, expected, materialized=True)
            try:
                staging.rename(target)
            except OSError:
                # A separately started process may have published an equivalent
                # cache. It must pass the same byte-level check before reuse.
                current = _existing(target, expected)
                if current is None:
                    raise
                return target, *current
        verified = verify(target, expected, materialized=True)
        return target, *verified
