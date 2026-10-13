"""Resource sampling and isolated process ownership for the synthetic scale probe."""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from pathlib import Path

from tools.xstress.core import Server


class ScaleServer(Server):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stop_lock = threading.Lock()

    def env(self):
        temporary = self.dir / "tmp"
        temporary.mkdir(exist_ok=True)
        return {**super().env(), "JOB_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULE_ENABLED": "false",
                "AI_ENABLED": "false", "PLUGIN_DIRS": "[]", "TASK_QUEUE_BACKEND": "sync",
                "TMP": str(temporary), "TEMP": str(temporary), "TMPDIR": str(temporary)}

    def stop(self, hard=False):
        with self.stop_lock:
            super().stop(hard=hard)


def resource_sample(root: int) -> dict:
    """Count the actual app worker as well as a Windows venv launcher; no extra package needed."""
    if os.name != "nt":
        pairs, values = [], {}
        for path in Path("/proc").glob("[0-9]*"):
            try:
                fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
                pid, parent = int(path.name), int(fields[1])
                pairs.append((pid, parent))
                values[pid] = {"pid": pid, "rss": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                               "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")}
            except (OSError, ValueError, IndexError):
                continue
        memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        available = int(memory["MemAvailable"].split()[0]) * 1024
    else:
        from ctypes import wintypes as w

        class Entry(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                        ("heap", ctypes.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                        ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD), ("exe", w.WCHAR * 260)]

        class Counters(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged",
                                                    "nonpaged", "private_bytes", "peak_private")]

        class Memory(ctypes.Structure):
            _fields_ = [("length", w.DWORD), ("load", w.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in ("total", "available", "total_page", "available_page",
                                                      "total_virtual", "available_virtual", "extended")]

        kernel, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
        signatures = {
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Process32FirstW": ([w.HANDLE, ctypes.POINTER(Entry)], w.BOOL),
            "Process32NextW": ([w.HANDLE, ctypes.POINTER(Entry)], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "GetProcessTimes": ([w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL),
            "GlobalMemoryStatusEx": ([ctypes.POINTER(Memory)], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            getattr(kernel, name).argtypes, getattr(kernel, name).restype = args, result
        psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        entry, pairs, values = Entry(), [], {}
        entry.size = ctypes.sizeof(entry)
        try:
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                pairs.append((entry.pid, entry.parent))
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        family = descendants(root, pairs)
        for pid in family:
            handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
            if not handle:
                continue
            try:
                counters = Counters()
                counters.cb = ctypes.sizeof(counters)
                if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    continue
                stamps = [w.FILETIME() for _ in range(4)]
                times_ok = kernel.GetProcessTimes(handle, *(ctypes.byref(stamp) for stamp in stamps))
                cpu = sum((stamp.dwHighDateTime << 32) + stamp.dwLowDateTime for stamp in stamps[2:]) / 1e7
                values[pid] = {"pid": pid, "rss": counters.rss, "peak_rss": counters.peak_rss,
                               "private_bytes": counters.private_bytes, "cpu_seconds": cpu if times_ok else None}
            finally:
                kernel.CloseHandle(handle)
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ctypes.WinError(ctypes.get_last_error())
        available = memory.available
    processes = [values[pid] for pid in sorted(descendants(root, pairs)) if pid in values]
    return {"processes": processes, "rss": sum(p["rss"] for p in processes), "available_bytes": available,
            "cpu_seconds": sum(p.get("cpu_seconds") or 0 for p in processes),
            "private_bytes": sum(p.get("private_bytes", 0) for p in processes)}


def descendants(root, pairs):
    family = {root}
    while True:
        children = {child for child, parent in pairs if parent in family}
        if children <= family:
            return family
        family |= children


class Monitor:
    """A continuously sampled guard: a stopped phase is an explicit failure, never a pass."""

    def __init__(self, server, out, *, memory_mib=2048, minimum_free_mib=1024, seconds=600):
        self.server, self.out = server, out
        self.maximum = memory_mib * 1024**2
        self.minimum = minimum_free_mib * 1024**2
        self.seconds = seconds
        self.done = threading.Event()
        self.phase = "startup"
        self.failure = None
        self.peaks = {}
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="scale-resource-guard", daemon=True)
        self.thread.start()

    def _run(self):
        started = time.monotonic()
        try:
            with (self.out / "resources.jsonl").open("a", encoding="utf-8") as log:
                while not self.done.is_set():
                    proc = self.server.proc
                    if proc is not None and proc.poll() is None:
                        sample = resource_sample(proc.pid)
                        peak = self.peaks.setdefault(self.phase, {"rss": 0, "private_bytes": 0, "cpu_seconds": 0})
                        for field in ("rss", "private_bytes", "cpu_seconds"):
                            peak[field] = max(peak[field], sample[field])
                        peak.setdefault("cpu_start_seconds", sample["cpu_seconds"])
                        peak["cpu_delta_seconds"] = peak["cpu_seconds"] - peak["cpu_start_seconds"]
                        log.write(json.dumps({"elapsed": time.monotonic() - started, "phase": self.phase, **sample}) + "\n")
                        log.flush()
                        if not sample["processes"]:
                            raise RuntimeError("The process tree could not be measured")
                        if sample["rss"] > self.maximum or sample["private_bytes"] > self.maximum:
                            raise RuntimeError(f"App process tree exceeded {self.maximum} bytes")
                        if sample["available_bytes"] < self.minimum:
                            raise RuntimeError(f"Available system memory fell below {self.minimum} bytes")
                    if time.monotonic() - started > self.seconds:
                        raise RuntimeError(f"Stage exceeded {self.seconds} seconds")
                    self.done.wait(0.25)
        except Exception as exc:
            self.fail(str(exc))

    def fail(self, reason):
        self.failure = self.failure or reason
        (self.out / "guard-failure.txt").write_text(self.failure, encoding="utf-8")
        self.server.stop(hard=True)

    def check(self):
        if self.failure:
            raise RuntimeError(self.failure)

    def close(self):
        self.done.set()
        if self.thread:
            self.thread.join(timeout=15)
            if self.thread.is_alive():
                raise RuntimeError("Resource monitor did not finish")
