"""Pinned bundle tampering, archive boundaries and process resource budgets."""
import hashlib
import io
import json
import stat
import sys
import tarfile
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

from backend.services.e_invoice import asset_bundle, posix_worker


@pytest.mark.parametrize('name', ['', '.', '../file', 'a/../../file', '/absolute', 'C:/file', 'a\\b', 'x\x00y'])
def test_bundle_member_paths_are_confined(name):
    with pytest.raises(ValueError):
        asset_bundle.safe_name(name)


def test_zip_symlink_and_duplicate_names_are_rejected(tmp_path):
    archive = tmp_path / 'input.zip'
    entry = ZipInfo('linked')
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive, 'w') as target:
        target.writestr(entry, '../outside')
    with pytest.raises(ValueError, match='Ambiguous'):
        list(asset_bundle.extracted({'extract': 'runtime'}, archive))
    with ZipFile(archive, 'w') as target:
        target.writestr('same', b'a')
        with pytest.warns(UserWarning):
            target.writestr('same', b'b')
    with pytest.raises(ValueError, match='Ambiguous'):
        list(asset_bundle.extracted({'extract': 'runtime'}, archive))


@pytest.mark.parametrize('link', ['../../outside', '/outside', 'missing', 'legal'])
def test_tar_links_never_read_the_host_or_cycle(tmp_path, link):
    archive = tmp_path / 'input.tar.gz'
    with tarfile.open(archive, 'w:gz') as target:
        entry = tarfile.TarInfo('jre/legal')
        entry.type = tarfile.SYMTYPE
        entry.linkname = link
        target.addfile(entry)
    with pytest.raises(ValueError):
        list(asset_bundle.extracted({'extract': 'runtime'}, archive))


def test_tar_legal_links_are_materialized_from_verified_archive_bytes(tmp_path):
    archive = tmp_path / 'input.tar.gz'
    with tarfile.open(archive, 'w:gz') as target:
        entry = tarfile.TarInfo('jre/legal/text')
        entry.size = 4
        target.addfile(entry, io.BytesIO(b'text'))
        link = tarfile.TarInfo('jre/legal/alias')
        link.type = tarfile.SYMTYPE
        link.linkname = 'text'
        target.addfile(link)
    assert list(asset_bundle.extracted({'extract': 'runtime'}, archive)) == [
        ('runtime/jre/legal/text', b'text', False), ('runtime/jre/legal/alias', b'text', False)]


def test_rewritten_manifest_cannot_approve_modified_extracted_rules(tmp_path):
    archive = tmp_path / 'rules.zip'
    with ZipFile(archive, 'w') as target:
        target.writestr('rules.xsl', b'official pinned rules')
    asset = {'name': 'test-rules', 'filename': archive.name, 'sha256': asset_bundle.file_sha(archive), 'extract': 'rules'}
    expected = {'format': 'unit-test-pinned', 'platform': 'windows-x64', 'assets': [asset]}
    (tmp_path / 'rules').mkdir()
    (tmp_path / 'rules/rules.xsl').write_bytes(b'official pinned rules')
    files = {'rules.zip': asset['sha256'], 'rules/rules.xsl': hashlib.sha256(b'official pinned rules').hexdigest()}
    manifest: dict = {**expected, 'files': files}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    assert asset_bundle.verify(tmp_path, expected)[0] == manifest
    (tmp_path / 'rules/rules.xsl').write_bytes(b'changed rules')
    manifest['files']['rules/rules.xsl'] = hashlib.sha256(b'changed rules').hexdigest()
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='checksum'):
        asset_bundle.verify(tmp_path, expected)


def test_posix_limits_are_applied_before_owned_command_exec(tmp_path, monkeypatch):
    folder = tmp_path / 'immo-e-invoice-test'
    folder.mkdir()
    called = []
    class Executed(Exception):
        pass
    def execute(*args):
        called.append(('exec', args))
        raise Executed
    resources = SimpleNamespace(RLIMIT_AS=1, RLIMIT_CPU=2, RLIMIT_CORE=3, RLIMIT_FSIZE=4, RLIMIT_NOFILE=5,
        RLIM_INFINITY=-1, getrlimit=lambda name: (-1, 64 if name == 5 else -1),
        setrlimit=lambda name, limits: called.append((name, limits)))
    monkeypatch.setitem(sys.modules, 'resource', resources)
    monkeypatch.setattr(posix_worker, 'os', SimpleNamespace(name='posix', environ={'E_INVOICE_LIMIT_DIR': str(folder)}, execvpe=execute))
    with pytest.raises(Executed):
        posix_worker.main([str(folder), 'extract', '30', sys.executable, 'owned-worker'])
    assert called[:-1] == [(1, (768 * 1024 * 1024,) * 2), (2, (30, 30)), (3, (0, 0)),
                          (4, (8 * 1024 * 1024,) * 2), (5, (64, 64))]
    assert called[-1][0] == 'exec'
