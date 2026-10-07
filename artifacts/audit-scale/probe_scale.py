"""Bounded read-only product audit: disposable SQLite, real ephemeral HTTP server.

Run with the verification Python. Product source is never changed. Seeding uses
sqlite3 (real storage format); API assertions are checked against independent SQL.
"""
from __future__ import annotations

import ctypes
import argparse
import json
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tools.xstress.core import PASSWORD, Findings, Server, setup_users


class ProbeServer(Server):
    """Pin every writable setting to this disposable instance, even with inherited test settings."""

    def env(self):
        return {**super().env(), "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false",
                "UPLOADS_DIR": str(self.dir / "uploads"), "BACKUP_DIR": str(self.dir / "backups"),
                "INTEGRATION_STATE_FILE": str(self.dir / "integrations.json"),
                "LOG_FILE": str(self.dir / "application.log"), "AI_ENABLED": "false",
                "IMMO_TESTVERSION": "false", "AUTO_MIGRATE": "false", "TASK_QUEUE_BACKEND": "sync"}

    def stop(self, hard=False):
        # The Windows venv launcher can have a real Python child. Only kill the
        # tree rooted at our own disposable Popen; never target a shared port.
        if os.name == "nt" and self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            self.proc.wait(timeout=15)
            self.proc = None
        else:
            super().stop(hard=hard)


def rss_bytes(pid):
    if os.name != "nt":
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        return None
    c = Counters()
    c.cb = ctypes.sizeof(c)
    try:
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
            return None
        return {"rss": c.WorkingSetSize, "peak_rss": c.PeakWorkingSetSize,
                "private_bytes": c.PagefileUsage}
    finally:
        kernel.CloseHandle(handle)


def tree_memory(pid):
    if os.name != "nt":
        return None
    from ctypes import wintypes
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    pairs = []
    try:
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            pairs.append((entry.th32ProcessID, entry.th32ParentProcessID))
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    family = {pid}
    while True:
        children = {child for child, parent in pairs if parent in family}
        if children <= family:
            break
        family |= children
    measurements = [{"pid": member, **value} for member in sorted(family)
                    if (value := rss_bytes(member)) is not None]
    return {"processes": measurements, "rss": sum(m["rss"] for m in measurements),
            "private_bytes": sum(m["private_bytes"] for m in measurements)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--paged-only", action="store_true", help="Skip current full-table scans and restart")
    args = parser.parse_args()
    if args.rows % 2000 or args.rows < 12000:
        parser.error("Rows must be a multiple of 2000 and at least 12000")
    target = REPO / "artifacts" / "audit-scale" / ("data-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
    target.mkdir(parents=True)
    server = ProbeServer(target, "main")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    output = {"head": head, "source_has_uncommitted_changes": bool(subprocess.run(
                  ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, check=True).stdout),
              "platform": platform.platform(), "python": sys.version, "sqlite": sqlite3.sqlite_version,
              "cpu_count": os.cpu_count(), "processor": platform.processor(), "seed": 1007,
              "rows": {"bookings": args.rows, "documents": 12000, "tasks": 12000},
              "paged_only": args.paged_only, "timings": []}
    start = time.perf_counter()
    def timed(label, func):
        t0 = time.perf_counter()
        value = func()
        elapsed = time.perf_counter() - t0
        memory = tree_memory(server.proc.pid) if server.proc else None
        output["timings"].append({"label": label, "seconds": round(elapsed, 6), "memory": memory})
        print(json.dumps(output["timings"][-1]), flush=True)
        return value
    try:
        timed("fresh_start", lambda: server.start(timeout=20))
        users = setup_users(server, Findings())
        owner = users["owner"]
        portfolio = owner.ok("POST", "/portfolios", {"name": "Scale probe"})
        account = owner.ok("POST", "/accounts", {"portfolio_id": portfolio["id"], "name": "Scale Bank",
                                                   "account_type": "bank"})
        tenant = owner.ok("POST", "/tenants", {"full_name": "Scale probe tenant"})
        def seed():
            with sqlite3.connect(server.db_file) as db:
                for offset in range(0, args.rows, 2000):
                    db.executemany("INSERT INTO bookings(id,account_id,tenant_id,booking_date,amount,status,payment_text,created_at,updated_at) VALUES(?,?,?,?,1,'open',?,'2026-10-07','2026-10-07')", [
                        (f"b-{i:08}", account["id"], tenant["id"] if i % 1000 == 0 else None,
                         "2026-01-01" if i < 10000 else "2026-10-07", "needle-last-booking" if i == args.rows - 1 else f"Booking {i}")
                        for i in range(offset, offset + 2000)])
                    db.commit()
                for offset in range(0, 12000, 2000):
                    db.executemany("INSERT INTO documents(id,tenant_id,title,file_url,created_at,updated_at) VALUES(?,?,?,?, '2026-10-07','2026-10-07')", [
                        (f"d-{i:08}", tenant["id"], f"Scale document {i}", f"/files/nonexistent-probe-{i}.pdf")
                        for i in range(offset, offset + 2000)])
                    db.executemany("INSERT INTO tasks(id,title,status,priority,created_at,updated_at) VALUES(?,?,'open','medium','2026-10-07','2026-10-07')", [
                        (f"t-{i:08}", f"Scale task {i}") for i in range(offset, offset + 2000)])
                    db.commit()
        timed(f"seed_{args.rows}_bookings_12k_docs_12k_tasks", seed)
        with sqlite3.connect(server.db_file) as db:
            output["expected_filtered_count"] = db.execute("SELECT COUNT(*) FROM bookings WHERE booking_date='2026-10-07'").fetchone()[0]
            output["expected_sum"] = timed("sqlite_sum_all", lambda: db.execute("SELECT SUM(amount) FROM bookings").fetchone()[0])
            output["tenant_plan"] = db.execute("EXPLAIN QUERY PLAN SELECT * FROM bookings WHERE tenant_id=?", (tenant["id"],)).fetchall()
        filtered = timed("date_filter_page", lambda: owner.ok("GET", "/bookings?date_from=2026-10-07&date_to=2026-10-07&limit=200"))
        output["date_filtered_actual_count"] = len(filtered) if isinstance(filtered, list) else filtered
        assert [b["id"] for b in filtered] == [f"b-{i:08}" for i in range(10000, 10200)]
        filtered_tail = timed("date_filter_tail", lambda: owner.ok("GET", f"/bookings?date_from=2026-10-07&date_to=2026-10-07&skip={args.rows - 10010}&limit=200"))
        output["date_filtered_tail_ids"] = [b["id"] for b in filtered_tail]
        assert output["date_filtered_tail_ids"] == [f"b-{i:08}" for i in range(args.rows - 10, args.rows)]
        end_page = timed(f"unfiltered_offset_{args.rows - 10}", lambda: owner.ok("GET", f"/bookings?skip={args.rows - 10}&limit=1000"))
        output["last_page_ids"] = [b["id"] for b in end_page or []]
        assert output["last_page_ids"] == [f"b-{i:08}" for i in range(args.rows - 10, args.rows)]
        docs = timed("tenant_docs_offset_11990", lambda: owner.ok("GET", f"/tenants/{tenant['id']}/documents?skip=11990&limit=25"))
        output["tenant_document_tail"] = {"count": len(docs.get("items", [])), "total": docs.get("total"), "has_more": docs.get("has_more")}
        if not args.paged_only:
            summary = timed("cold_summary", lambda: owner.ok("GET", "/reports/summary"))
            output["summary_total"] = summary.get("finance", {}).get("bookingsTotal") if isinstance(summary, dict) else summary
            search = timed("search_single_hit_at_tail", lambda: owner.ok("GET", "/search?q=needle-last-booking&semantic=false"))
            output["search_tail_count"] = search.get("count") if isinstance(search, dict) else search
            timed("dashboard_12k_docs_12k_tasks", lambda: owner.ok("GET", "/dashboard/stats"))
        # One independent client per simultaneous request; this is bounded to 20 requests.
        import httpx
        clients = [httpx.Client(timeout=15, headers={"Authorization": f"Bearer {owner.token}"}) for _ in range(10)]
        gate = threading.Barrier(10)
        def read(pair):
            i, client = pair
            gate.wait(timeout=10)
            t0 = time.perf_counter()
            skip = i * 200
            resp = client.get(server.base + "/bookings?date_from=2026-10-07&date_to=2026-10-07&limit=200&skip=" + str(skip))
            rows = resp.json()
            exact = resp.status_code == 200 and [row["id"] for row in rows] == [
                f"b-{j:08}" for j in range(10000 + skip, 10200 + skip)]
            return {"status": resp.status_code, "seconds": time.perf_counter() - t0,
                    "count": len(rows), "expected_ids_match": exact}
        with ThreadPoolExecutor(10) as pool:
            output["ten_clients_paged"] = timed("ten_clients_200_bookings", lambda: list(pool.map(read, enumerate(clients))))
        assert all(row["expected_ids_match"] for row in output["ten_clients_paged"])
        latencies = sorted(row["seconds"] for row in output["ten_clients_paged"])
        output["ten_clients_latency_seconds"] = {"p50": statistics.median(latencies), "p95": latencies[-1],
                                                 "max": latencies[-1], "samples": len(latencies)}
        gate = threading.Barrier(10)
        def report(pair):
            i, client = pair
            gate.wait(timeout=10)
            t0 = time.perf_counter()
            resp = client.get(server.base + "/reports/summary")
            return {"status": resp.status_code, "seconds": time.perf_counter() - t0,
                    "sum": resp.json().get("finance", {}).get("bookingsTotal")}
        if not args.paged_only:
            with ThreadPoolExecutor(10) as pool:
                output["ten_clients_summary"] = timed("ten_clients_summary", lambda: list(pool.map(report, enumerate(clients))))
        for client in clients:
            client.close()
        if not args.paged_only:
            server.stop()
            timed(f"restart_{args.rows}", lambda: server.start(timeout=20))
        output["db_bytes"] = server.db_file.stat().st_size
        output["assertions_passed"] = True
    except Exception as exc:
        output["error"] = repr(exc)
        raise
    finally:
        server.stop()
        output["elapsed_seconds"] = time.perf_counter() - start
        (target / "measurements.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(str(target / "measurements.json"), flush=True)


if __name__ == "__main__":
    main()
