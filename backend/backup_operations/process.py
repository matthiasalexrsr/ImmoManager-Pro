"""Read-only native process witnesses; never terminate by an untrusted PID.

Windows uses a process object handle and GetProcessTimes creation identity;
Linux uses pidfd_open plus the boot/start identity from procfs. These handles
remain bound to the original process even when the OS later recycles its PID.
"""

import os
import time
from pathlib import Path

from .plan import BackupOperationError


def _windows_api():
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    api.GetProcessTimes.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    return api


class ProcessWitness:
    def __init__(self, pid: int, expected: str | None = None):
        if type(pid) is not int or pid <= 0:
            raise BackupOperationError("managed_process_identity_invalid")
        self.handle = None
        self.api = None
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                self.api = _windows_api()
                self.handle = self.api.OpenProcess(0x101000, False, pid)
                if not self.handle:
                    raise OSError(ctypes.get_last_error())
                values = [wintypes.FILETIME() for _ in range(4)]
                if not self.api.GetProcessTimes(self.handle, *(ctypes.byref(value) for value in values)):
                    raise OSError(ctypes.get_last_error())
                self.birth = "windows:" + str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
            else:
                opener = getattr(os, "pidfd_open", None)
                if opener is None:
                    raise BackupOperationError("native_process_witness_unavailable")
                self.handle = opener(pid, 0)
                boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
                self.birth = "linux:" + boot + ":" + fields[19]
            if expected is not None and self.birth != expected:
                raise BackupOperationError("managed_process_identity_changed")
        except (OSError, ValueError, IndexError):
            self.close()
            raise BackupOperationError("managed_process_witness_unavailable") from None
        except BaseException:
            self.close()
            raise

    def wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            milliseconds = min(0xfffffffe, max(0, int((deadline - time.monotonic()) * 1000)))
            if self.api is not None:
                result = self.api.WaitForSingleObject(self.handle, milliseconds)
                if result == 0:
                    return True
                if result != 258:
                    raise BackupOperationError("managed_process_wait_failed")
            else:
                import select
                poll = getattr(select, "poll")()
                poll.register(self.handle, getattr(select, "POLLIN"))
                events = poll.poll(milliseconds)
                if events:
                    if not events[0][1] & getattr(select, "POLLIN"):
                        raise BackupOperationError("managed_process_wait_failed")
                    return True
            if time.monotonic() >= deadline:
                return False

    def close(self):
        if self.handle is not None:
            if self.api is not None:
                if self.handle:
                    self.api.CloseHandle(self.handle)
            else:
                os.close(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def current_process_identity():
    with ProcessWitness(os.getpid()) as witness:
        return {"pid": os.getpid(), "birth": witness.birth}
