"""Fail-closed license/source packaging for the pinned invoice toolchain."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from backend.services.e_invoice.asset_bundle import file_sha, safe_name, verify
from backend.services.filesystem_paths import filesystem_path
from tools.prepare_e_invoice import fetch

ROOT = Path(__file__).resolve().parents[1]


def generate(output: Path) -> list[dict]:
    inputs = ROOT / 'packaging/e-invoice-notices'
    manifest = json.loads((inputs / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['format'] != 'immomanager-e-invoice-notices/1':
        raise RuntimeError('Unreviewed invoice notice inventory')
    target = filesystem_path(Path(output).resolve() / 'e-invoice')
    target.mkdir(parents=True, exist_ok=True)
    expected = {'manifest.json'}
    for entry in manifest['files']:
        name = safe_name(entry['file'])
        source = inputs / name
        if source.is_symlink() or file_sha(source) != entry['sha256']:
            raise RuntimeError('Invoice notice checksum mismatch: ' + name)
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        expected.add(name)
    for entry in manifest['sources']:
        path = fetch(entry, ROOT / 'artifacts/e-invoice-sources')
        name = 'sources/' + safe_name(entry['filename'])
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        expected.add(name)
    # The public catalog must also contain the actual JRE's third-party legal
    # notices. Never infer their contents from the JRE's umbrella GPL license.
    bundle = filesystem_path(ROOT / 'artifacts/e-invoice')
    runtime, _ = verify(bundle)
    runtime_files = []
    for name, checksum in runtime['files'].items():
        if not name.startswith('runtime/') or '/legal/' not in name:
            continue
        published = 'runtime-legal/' + name.removeprefix('runtime/')
        destination = target / published
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle / name, destination)
        if file_sha(destination) != checksum:
            raise RuntimeError('Runtime notice checksum mismatch')
        expected.add(published)
        runtime_files.append({'file': published, 'sha256': checksum})
    if not runtime_files:
        raise RuntimeError('The packaged runtime has no verified legal notices')
    manifest['runtime'] = {'platform': runtime['platform'], 'files': runtime_files}
    actual = {path.relative_to(target).as_posix() for path in target.rglob('*') if path.is_file()}
    if actual - expected:
        raise RuntimeError('Stale invoice notice files; prepare a fresh output directory')
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return [{**row, 'notice': 'e-invoice/README.txt'} for row in manifest['components']]


def catalog(output: Path, components: list[dict]) -> None:
    """Only published package files enter the read-only public license catalog."""
    import hashlib

    output = filesystem_path(Path(output).resolve())
    files = []
    for path in sorted(output.rglob('*')):
        if not path.is_file() or path == output / 'catalog.json':
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(output):
            raise RuntimeError('License catalog contains a link outside the distribution')
        name = path.relative_to(output).as_posix()
        files.append({'id': hashlib.sha256(name.encode()).hexdigest(), 'path': name,
                      'bytes': path.stat().st_size, 'sha256': file_sha(path)})
    (output / 'catalog.json').write_text(json.dumps({'format': 'immomanager-public-notices/1',
        'components': [{key: row.get(key) for key in ('ecosystem', 'name', 'version', 'license', 'notice')} for row in components],
        'files': files}, ensure_ascii=False, indent=2), encoding='utf-8')


def verify_catalog(output: Path) -> int:
    """Verify the assembled distribution, not merely the build's input folder."""
    import hashlib

    root = filesystem_path(Path(output).resolve())
    value = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
    if value['format'] != 'immomanager-public-notices/1':
        raise RuntimeError('Unrecognized assembled license catalog')
    names = set()
    for entry in value['files']:
        name = safe_name(entry['path'])
        path = root / name
        if name in names or hashlib.sha256(name.encode()).hexdigest() != entry['id']:
            raise RuntimeError('Ambiguous assembled license catalog')
        names.add(name)
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size != entry['bytes'] or file_sha(path) != entry['sha256']:
                raise RuntimeError('Changed assembled license/source file: ' + name)
        except OSError:
            raise RuntimeError('Missing assembled license/source file: ' + name) from None
    if not names:
        raise RuntimeError('Empty assembled license catalog')
    return len(names)
