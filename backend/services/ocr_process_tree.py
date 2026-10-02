"""Native ownership of a local OCR tool tree, without a shell or global settings.

Windows: assign the suspended process to a kill-on-close job before any code
runs. This includes launcher children and enforces aggregate committed memory.
POSIX: a fresh process group is killed at completion as well as on cancellation.
"""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
from ctypes import wintypes
from pathlib import Path


def _windows_error() -> OSError:
    return getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters)] + [
        (name, ctypes.c_size_t) for name in (
            "ProcessMemoryLimit", "JobMemoryLimit", "PeakProcessMemoryUsed", "PeakJobMemoryUsed",
        )
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]


class ProcessTree:
    def __init__(self, memory_bytes: int):
        self.handle = None
        self.kernel = None
        self.children: dict[int, int] = {}
        if os.name != "nt":
            return
        kernel = self.kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = arguments, result
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise _windows_error()
        limits = _ExtendedLimits()
        # KILL_ON_JOB_CLOSE + JOB_MEMORY: no breakaway flags or shared job name.
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x200
        limits.JobMemoryLimit = max(1, memory_bytes)
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = _windows_error()
            self.close()
            raise error

    @property
    def creation_options(self) -> dict:
        if os.name == "nt":
            return {"creationflags": 0x08000000 | 0x00000004}  # CREATE_NO_WINDOW | CREATE_SUSPENDED
        return {"start_new_session": True}

    def attach(self, process: subprocess.Popen) -> None:
        if self.kernel is None:
            return
        kernel = self.kernel
        if not kernel.AssignProcessToJobObject(self.handle, int(getattr(process, "_handle"))):
            raise _windows_error()
        snapshot = kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot in (None, ctypes.c_void_p(-1).value):
            raise _windows_error()
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process.pid:
                    thread = kernel.OpenThread(2, False, entry.th32ThreadID)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise _windows_error()
                    try:
                        if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise _windows_error()
                        return
                    finally:
                        kernel.CloseHandle(thread)
                found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Suspended OCR worker thread was not found")
        finally:
            kernel.CloseHandle(snapshot)

    def memory(self, process: subprocess.Popen) -> int | None:
        if self.kernel is not None:
            counters = _ExtendedLimits()
            if self.kernel.QueryInformationJobObject(self.handle, 9, ctypes.byref(counters), ctypes.sizeof(counters), None):
                return int(counters.PeakJobMemoryUsed)
            return None
        # Linux observation includes descendants; it is sampled, not RLIMIT_AS.
        # Other POSIX systems retain pixel/input preflight but lack /proc metrics.
        total = 0
        pending = [process.pid]
        seen = set()
        while pending:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            try:
                status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
                for line in status.splitlines():
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1]) * 1024
                # Linux children belong to the thread that created them, not
                # necessarily the main thread. Deduplicate shared discoveries.
                for child_file in Path(f"/proc/{pid}/task").glob("*/children"):
                    try:
                        pending.extend(int(child) for child in child_file.read_text().split())
                    except OSError:
                        continue
                opener = getattr(os, "pidfd_open", None)
                sender = getattr(signal, "pidfd_send_signal", None)
                if pid != process.pid and pid not in self.children and opener and sender:
                    # A pidfd keeps this exact observed child addressable even
                    # after setsid/reparenting, without killing a reused PID.
                    stat_file = Path(f"/proc/{pid}/stat")
                    identity = stat_file.read_text().rsplit(")", 1)[1].split()[19]
                    descriptor = opener(pid, 0)
                    try:
                        same = stat_file.read_text().rsplit(")", 1)[1].split()[19] == identity
                    except OSError:
                        same = False
                    if same:
                        self.children[pid] = descriptor
                    else:
                        os.close(descriptor)
            except OSError:
                continue
        return total or None

    def close(self, process: subprocess.Popen | None = None) -> None:
        if self.handle is not None and self.kernel is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif process is not None and os.name != "nt":
            for descriptor in self.children.values():
                try:
                    getattr(signal, "pidfd_send_signal")(descriptor, getattr(signal, "SIGKILL"))
                except ProcessLookupError:
                    pass
                finally:
                    os.close(descriptor)
            self.children.clear()
            try:
                getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
            except ProcessLookupError:
                pass
