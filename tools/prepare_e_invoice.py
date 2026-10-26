"""Build-only preparation of the reviewed local validator/runtime distribution.

Network downloads are allowed only here; application startup never fetches code.
Every upstream input and the deterministic resulting JAR are pinned by SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.e_invoice.asset_bundle import configuration, extracted, file_sha, safe_name, verify  # noqa: E402
from backend.services.filesystem_paths import filesystem_path  # noqa: E402
from tools.repackage_e_invoice import derive, kosit_cli  # noqa: E402


def fetch(entry: dict, cache: Path) -> Path:
    cache = filesystem_path(cache.resolve())
    filename = safe_name(entry['filename'])
    if '/' in filename:
        raise ValueError('Download filename must be a basename')
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / filename
    if path.is_file() and file_sha(path) == entry['sha256']:
        return path
    request = urllib.request.Request(entry['url'], headers={'User-Agent': 'ImmoManager-reviewed-release-preparation'})
    with tempfile.NamedTemporaryFile(dir=cache, delete=False, suffix='.part') as temporary:
        partial = Path(temporary.name)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                count = 0
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > 512 * 1024 * 1024:
                        raise RuntimeError('Release input too large')
                    temporary.write(chunk)
            temporary.close()
            if file_sha(partial) != entry['sha256']:
                raise RuntimeError('Release checksum mismatch: ' + filename)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return path


def prepare(target: Path, *, target_platform: str | None = None, cache: Path | None = None) -> dict:
    target = target.resolve()
    cache = (cache or target.parent / 'e-invoice-downloads').resolve()
    if target == cache or cache.is_relative_to(target):
        raise ValueError('Build cache must be outside the runtime directory')
    target.mkdir(parents=True, exist_ok=True)
    config = configuration(target_platform=target_platform)
    files = {}
    for asset in config['assets']:
        destination = target / safe_name(asset['filename'])
        if 'derive' in asset:
            recipe = asset['derive']
            base = fetch(recipe['base'], cache)
            if not destination.is_file() or file_sha(destination) != asset['sha256']:
                if recipe['recipe'] == 'mustang-security-1':
                    replacements = [(entry, fetch(entry, cache)) for entry in recipe['replacements']]
                    derive(base, replacements, destination)
                elif recipe['recipe'] == 'kosit-cli-1':
                    kosit_cli(base, destination)
                else:
                    raise RuntimeError('Unreviewed package transformation')
        else:
            source = fetch(asset, cache)
            if not destination.is_file() or file_sha(destination) != asset['sha256']:
                shutil.copyfile(source, destination)
        if file_sha(destination) != asset['sha256']:
            raise RuntimeError('Reproducible output mismatch: ' + asset['name'])
        files[asset['filename']] = asset['sha256']
        for relative, content, executable in extracted(asset, destination):
            out = target / relative
            if out.is_symlink() or not out.resolve().is_relative_to(target):
                raise RuntimeError('Unsafe output path')
            filesystem_path(out.parent).mkdir(parents=True, exist_ok=True)
            filesystem_path(out).write_bytes(content)
            if os.name != 'nt':
                out.chmod(0o755 if executable else 0o644)
            files[relative] = hashlib.sha256(content).hexdigest()
        print(asset['name'] + ' verified', flush=True)
    manifest = {**config, 'files': files}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    verify(target, config)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    parser.add_argument('--platform', choices=('windows-x64', 'linux-x64'))
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    prepare(args.target, target_platform=args.platform, cache=args.cache)
