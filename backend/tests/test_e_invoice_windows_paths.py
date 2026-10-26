"""Real Windows path/ACL boundary, with tiny pinned bundles and no JVM mocks for hashing."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.services.e_invoice import asset_bundle, validator
from backend.services.filesystem_paths import filesystem_path

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows launcher path and DACL boundary')


@pytest.fixture
def pinned_long_bundle(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='immo-java-test-', dir=filesystem_path(tempfile.gettempdir())) as directory:
        base = validator._windows_display_path(directory)
        root = base / ('long-installation-' * 6) / ('long-application-' * 5)
        filesystem_path(root).mkdir(parents=True)
        archive = filesystem_path(root / 'runtime.zip')
        with ZipFile(archive, 'w') as target:
            target.writestr('jre/bin/java.exe', b'pinned java')
            target.writestr('jre/bin/server/jvm.dll', b'pinned jvm')
            target.writestr('jre/legal/LICENSE', b'license')
        asset = {'name': 'test-runtime', 'filename': 'runtime.zip', 'sha256': asset_bundle.file_sha(archive),
                 'extract': 'runtime'}
        expected = {'format': 'windows-path-unit-test', 'platform': 'windows-x64', 'assets': [asset]}
        files = {'runtime.zip': asset['sha256']}
        for name, content, _ in asset_bundle.extracted(asset, archive):
            output = filesystem_path(root / name)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            files[name] = hashlib.sha256(content).hexdigest()
        manifest = {**expected, 'files': files}
        filesystem_path(root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        verified, digest = asset_bundle.verify(root, expected)
        monkeypatch.setattr(validator, 'verify_bundle', lambda path: asset_bundle.verify(path, expected))
        java = Path('runtime/jre/bin/java.exe')
        assert not validator._runtime_path_fits(root, java)
        yield root, verified, digest, java


def test_existing_short_alias_runs_same_verified_bundle_without_copy(pinned_long_bundle, monkeypatch):
    root, manifest, digest, java = pinned_long_bundle
    alias = validator._short_windows_path(root)
    if alias is None or not validator._runtime_path_fits(alias, java):
        pytest.skip('This volume does not provide an 8.3 alias; covered by the fallback tests')
    monkeypatch.setattr(validator, '_copy_verified_bundle', lambda *args: pytest.fail('Short alias must avoid a copy'))
    with validator._execution_paths(root, manifest, digest, java) as (execution_root, work):
        assert execution_root == alias
        assert filesystem_path(execution_root).samefile(filesystem_path(root))
        assert validator._runtime_path_fits(execution_root, java)
        assert work.is_dir()
        policy = validator._policy(execution_root, work)
        assert execution_root.as_posix() in policy
        assert root.as_posix() not in policy
        assert 'SocketPermission' not in policy and 'AllPermission' not in policy
    assert not work.exists()


@pytest.mark.parametrize('interrupt', [False, True], ids=['normal-exit', 'exception'])
def test_disabled_short_names_copy_reverify_and_clean_owned_bundle(pinned_long_bundle, monkeypatch, interrupt):
    root, manifest, digest, java = pinned_long_bundle
    monkeypatch.setattr(validator, '_short_windows_path', lambda path: None)
    target = None
    class Interrupted(Exception):
        pass
    try:
        with validator._execution_paths(root, manifest, digest, java) as (target, work):
            assert target != root and target.parent == work.parent
            assert validator._runtime_path_fits(target, java)
            assert validator.verify_bundle(target) == (manifest, digest)
            (work / 'invoice.xml').write_bytes(b'private invoice')
            assert (target / java).read_bytes() == b'pinned java'
            if interrupt:
                raise Interrupted
    except Interrupted:
        assert interrupt
    assert target is not None and not target.parent.exists()
    assert filesystem_path(root / java).read_bytes() == b'pinned java'


def test_fallback_does_not_copy_uninventoried_files(pinned_long_bundle, monkeypatch):
    root, manifest, digest, java = pinned_long_bundle
    # A file added after bundle() verification must never enter the copied root.
    filesystem_path(root / 'application-secret.txt').write_text('do not copy', encoding='utf-8')
    monkeypatch.setattr(validator, '_short_windows_path', lambda path: None)
    with validator._execution_paths(root, manifest, digest, java) as (target, _work):
        assert not (target / 'application-secret.txt').exists()
        assert validator.verify_bundle(target) == (manifest, digest)


def test_changed_copy_is_rejected_before_execution_and_cleaned(pinned_long_bundle, monkeypatch):
    root, manifest, digest, java = pinned_long_bundle
    monkeypatch.setattr(validator, '_short_windows_path', lambda path: None)
    original = validator.shutil.copyfile
    destinations = []
    def corrupt(source, target, **kwargs):
        result = original(source, target, **kwargs)
        destinations.append(Path(target))
        if Path(target).name == 'jvm.dll':
            Path(target).write_bytes(b'tampered after source verification')
        return result
    monkeypatch.setattr(validator.shutil, 'copyfile', corrupt)
    with pytest.raises(validator.ValidatorUnavailable, match='temporäre Kopie'):
        with validator._execution_paths(root, manifest, digest, java):
            pytest.fail('No execution may occur after a failed copy verification')
    assert destinations and all(not target.exists() for target in destinations)
    assert filesystem_path(root / java.parent / 'server/jvm.dll').read_bytes() == b'pinned jvm'


def test_unusable_temp_path_is_actionable_and_never_launches_or_copies(pinned_long_bundle, monkeypatch):
    root, manifest, digest, java = pinned_long_bundle
    monkeypatch.setattr(validator, '_short_windows_path', lambda path: None)
    monkeypatch.setattr(validator, '_native_path_fits', lambda path: False)
    monkeypatch.setattr(validator, '_copy_verified_bundle', lambda *args: pytest.fail('Cannot copy to an overlong target'))
    with pytest.raises(validator.ValidatorUnavailable, match='TEMP/TMP.*kürzeren lokalen Ordner'):
        with validator._execution_paths(root, manifest, digest, java):
            pytest.fail('No execution may occur with an unusable temporary root')


def test_unc_temp_is_rejected_before_creating_a_directory(pinned_long_bundle, monkeypatch):
    root, manifest, digest, java = pinned_long_bundle
    monkeypatch.setattr(validator.tempfile, 'gettempdir', lambda: r'\\example.invalid\shared-temp')
    monkeypatch.setattr(validator.tempfile, 'TemporaryDirectory', lambda **kwargs: pytest.fail('No network work directory'))
    with pytest.raises(validator.ValidatorUnavailable, match='beschreibbaren lokalen Ordner'):
        with validator._execution_paths(root, manifest, digest, java):
            pytest.fail('No execution may occur on a remote TEMP')


def test_unwritable_temp_is_an_actionable_technical_error(pinned_long_bundle, monkeypatch):
    root, manifest, digest, java = pinned_long_bundle
    def unavailable(**kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr(validator.tempfile, 'TemporaryDirectory', unavailable)
    with pytest.raises(validator.ValidatorUnavailable, match='TEMP/TMP.*nicht beschreibbar'):
        with validator._execution_paths(root, manifest, digest, java):
            pytest.fail('No execution may occur without a private local temporary root')


def test_native_limit_counts_utf16_units_and_includes_jvm_suffix():
    # Astral characters consume two WCHARs in the launcher's native path.
    root = Path('C:/') / ('\U0001f600' * 104)
    java = Path('runtime/jre/bin/java.exe')
    assert len(str(root / java)) < validator.MAX_JAVA_NATIVE_PATH
    assert validator._native_path_fits(root / java)
    assert not validator._runtime_path_fits(root, java)


def test_private_temp_dacl_has_owner_system_only_and_is_inherited():
    import ctypes
    from ctypes import wintypes
    with tempfile.TemporaryDirectory(prefix='immo-java-acl-') as directory:
        root = Path(directory)
        validator._protect_windows_directory(root)
        child = root / 'invoice.xml'
        child.write_bytes(b'private')
        advapi = getattr(ctypes, 'WinDLL')('advapi32', use_last_error=True)
        kernel = getattr(ctypes, 'WinDLL')('kernel32', use_last_error=True)
        get = advapi.GetNamedSecurityInfoW
        get.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        get.restype = wintypes.DWORD
        convert = advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
        convert.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
        convert.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        for path in (root, child):
            descriptor, text = ctypes.c_void_p(), wintypes.LPWSTR()
            assert get(str(path), 1, 4, None, None, None, None, ctypes.byref(descriptor)) == 0
            try:
                assert convert(descriptor, 1, 4, ctypes.byref(text), None)
                value = text.value
                assert value is not None
                assert ';;;OW)' in value and ';;;SY)' in value
                assert not any(sid in value for sid in (';;;WD)', ';;;BU)', ';;;AU)'))
                if path == root:
                    assert value.startswith('D:P')
                else:
                    assert 'ID;' in value
            finally:
                if text:
                    kernel.LocalFree(text)
                if descriptor:
                    kernel.LocalFree(descriptor)
