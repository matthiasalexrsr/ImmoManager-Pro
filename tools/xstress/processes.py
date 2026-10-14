"""Owned process groups; Windows jobs also contain Python launcher children."""

import os
import signal
import subprocess
import time


class WindowsJob:
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w

        self.c = c
        self.k = c.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, c.c_void_p], w.BOOL),
            "Thread32Next": ([w.HANDLE, c.c_void_p], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.k, name)
            fn.argtypes, fn.restype = args, result

        class Limits(c.Structure):
            _fields_ = [("user", c.c_int64), ("job_user", c.c_int64), ("flags", w.DWORD),
                        ("min_ws", c.c_size_t), ("max_ws", c.c_size_t), ("active", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class Extended(c.Structure):
            _fields_ = [("basic", Limits), ("io", c.c_uint64 * 6), ("memory", c.c_size_t * 4)]

        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(self.handle, 9, c.byref(info), c.sizeof(info)):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def assign_and_resume(self, proc):
        c, k = self.c, self.k
        if not k.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise c.WinError(c.get_last_error())

        class ThreadEntry(c.Structure):
            _fields_ = [(name, c.c_ulong) for name in
                        ("size", "usage", "id", "owner", "base_priority", "delta_priority", "flags")]

        snapshot = k.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = c.sizeof(entry)
            found = k.Thread32First(snapshot, c.byref(entry))
            while found:
                if entry.owner == proc.pid:
                    thread = k.OpenThread(2, False, entry.id)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise c.WinError(c.get_last_error())
                    try:
                        if k.ResumeThread(thread) == 0xFFFFFFFF:
                            raise c.WinError(c.get_last_error())
                        return
                    finally:
                        k.CloseHandle(thread)
                found = k.Thread32Next(snapshot, c.byref(entry))
            raise RuntimeError("Owned suspended process has no primary thread")
        finally:
            k.CloseHandle(snapshot)

    def stop(self, timeout=10):
        c, k = self.c, self.k
        if not k.TerminateJobObject(self.handle, 1):
            raise c.WinError(c.get_last_error())
        # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four LARGE_INTEGER + four DWORD.
        counters = (c.c_uint64 * 6)()
        deadline = time.monotonic() + timeout
        while True:
            if not k.QueryInformationJobObject(self.handle, 1, c.byref(counters), c.sizeof(counters), None):
                raise c.WinError(c.get_last_error())
            active = c.c_uint32.from_buffer(counters, 40).value
            if active == 0:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{active} owned processes did not exit")
            time.sleep(0.02)

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def start_owned(args, **kwargs):
    if os.name != "nt":
        return subprocess.Popen(args, start_new_session=True, **kwargs), None
    job = WindowsJob()
    proc = None
    try:
        # Suspend before assigning the job: no child can escape between launch and assignment.
        proc = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW | 4, **kwargs)
        job.assign_and_resume(proc)
        return proc, job
    except BaseException:
        if proc is not None:
            proc.kill()
            proc.wait(timeout=10)
        job.close()
        raise


def stop_owned(proc, job, hard=False):
    if job is not None:
        try:
            job.stop()
            proc.wait(timeout=10)
        finally:
            job.close()
        return
    # Only the session created by start_owned is addressed, never processes by name.
    try:
        os.killpg(proc.pid, signal.SIGKILL if hard else signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
    if not hard:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # reap descendants that ignored SIGTERM
        except ProcessLookupError:
            pass
