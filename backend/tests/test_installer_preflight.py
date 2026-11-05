"""Installer QA must refuse a live application before creating any fixture."""
import ctypes
import os
import sys
from uuid import uuid4

import pytest

from scripts import check_windows_installer as checker

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Native Windows installer mutex preflight')


def test_live_application_blocks_qa_before_paths_or_fixture_writes(monkeypatch, tmp_path):
    name = 'Local\\ImmoManagerPro.InstallerPreflightQA.' + uuid4().hex
    monkeypatch.setattr(checker, 'MUTEX', name)
    monkeypatch.setattr(checker, 'registered', lambda: False)
    monkeypatch.setattr(checker.tempfile, 'mkdtemp', lambda **options: pytest.fail('No fixture may be created before preflight'))
    monkeypatch.setattr(sys, 'argv', ['check_windows_installer.py', '--installer', str(tmp_path / 'missing.exe'),
                                   '--dist', str(tmp_path / 'missing-build'), '--work', str(tmp_path)])
    kernel = getattr(ctypes, 'WinDLL')('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, name)
    assert handle
    try:
        with pytest.raises(SystemExit, match='running; no installation started'):
            checker.main()
        # The read-only check must not release the real application's reference.
        with pytest.raises(SystemExit, match='running; no installation started'):
            checker.require_application_stopped()
    finally:
        kernel.CloseHandle(handle)
    checker.require_application_stopped()
    assert list(tmp_path.iterdir()) == []


def test_mutex_access_failure_is_not_treated_as_an_absent_application(monkeypatch):
    class UnreadableKernel:
        def __init__(self):
            self.OpenMutexW = self.open_mutex
            self.CloseHandle = self.close_handle

        @staticmethod
        def open_mutex(*args):
            getattr(ctypes, 'set_last_error')(5)  # ERROR_ACCESS_DENIED
            return None

        @staticmethod
        def close_handle(*args):
            pytest.fail('No handle was obtained')

    # Functions accept the ctypes signature attributes set by the real checker.
    kernel = UnreadableKernel()
    monkeypatch.setattr(checker.ctypes, 'WinDLL', lambda *args, **kwargs: kernel)
    with pytest.raises(SystemExit, match='Windows error 5'):
        checker.require_application_stopped()
