"""Disposable real-HTTP finance/search benchmark with independent, bounded-memory oracles.

    python -m tools.scale_finance_search --rows 100000
    python -m tools.scale_finance_search --rows 1000000 --mixed-seconds 60

Each invocation owns a fresh fixture and process tree. It never opens an existing app database.
The 240-month data is synthetic cardinality evidence, not twenty years of simulated workflows.
Results are checkpointed under artifacts/scale-finance-search; failures return a nonzero exit code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

from tools.scale_runtime import Monitor, ScaleServer
from tools.xstress.core import PASSWORD, REPO, fresh_directory

FIRST, LAST = "2006-01-01", "2025-12-31"
MONTHS = tuple(f"{2006 + i // 12:04d}-{1 + i % 12:02d}" for i in range(240))
STAMP = "2026-10-13 00:00:00"
FILTERS = {
    "all": {"date_from": FIRST, "date_to": LAST},
    "year": {"date_from": "2016-01-01", "date_to": "2016-12-31"},
    "portfolio": {"date_from": FIRST, "date_to": LAST, "portfolio_id": "p-0"},
    "property": {"date_from": FIRST, "date_to": LAST, "property_id": "prop-00"},
    "unit": {"date_from": FIRST, "date_to": LAST, "unit_id": "unit-000"},
}
SEARCH_QUERIES = ("tailmarker2026", "missing-marker-2026", "synthetic booking", "ÖZTÜRK", "100%_\\literal",
                  "export-bucket")
SOURCE_FILES = (
    "backend/routers/reports.py", "backend/services/report_service.py", "backend/services/finance_ledger.py",
    "backend/routers/search.py", "backend/services/global_search.py", "backend/routers/accounts.py",
    "backend/concurrency.py", "tools/scale_finance_search.py", "tools/scale_runtime.py", "tools/xstress/core.py",
)


def cents(value):
    """Only decode an API number, never perform the product's arithmetic in this oracle."""
    result = Decimal(str(value)) * 100
    if result != result.to_integral_value():
        raise AssertionError(f"Non-cent response: {value!r}")
    return int(result)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def exported_cents(value):
    require(not value.startswith("-"), "Negative CSV amount lacks spreadsheet escaping")
    return cents(value[1:] if value.startswith("'-") else value)


@dataclass(frozen=True)
class Row:
    id: str
    day: str
    amount: int
    side: str
    portfolio: int
    account: str
    property: str | None
    unit: str | None
    tenant: str | None
    category: str | None
    text: str
    reverses: str | None = None

    @property
    def effective_property(self):
        return self.property or (f"prop-{int(self.unit.split('-')[1]) % 30:02d}" if self.unit else None)


def fixture_row(i, rows):
    """An explicit ten-record recipe, including income and expense reversal pairs."""
    group, kind = divmod(i, 10)
    portfolio, unit = group % 3, group * 37 % 300
    income, expense = 10000 + group % 90001, 3301 + group % 700
    amount = (income, -income, -expense, expense, 1111, 3333, -2222, 100001, 4444, -5555)[kind]
    side = ("income", "income", "expense", "expense", "income", "income", "expense", "income",
            "income", "expense")[kind]
    category = f"cat-{portfolio}-{'income' if kind in (0, 1, 4) else 'expense'}" if kind in (0, 1, 2, 3, 4, 9) else None
    has_unit = kind in (0, 1, 7, 8)
    prop = f"prop-{unit % 30:02d}" if not has_unit or group % 2 else None
    text = f"Synthetic booking {i}"
    if i % 97 == 0:
        text += " export-bucket"
    if i % 997 == 11:
        text += " Öztürk"
    if i % 991 == 23:
        text += " 100%_\\literal"
    if i == rows - 1:
        text += " tailmarker2026"
    day = f"{MONTHS[group // 3 % 240]}-{1 + group // 720 % 28:02d}" if i != rows - 1 else LAST
    return Row(f"b-{i:010d}", day, amount, side, portfolio, f"acc-{group % 6}", prop,
               f"unit-{unit:03d}" if has_unit else None,
               f"tenant-{unit:03d}" if kind in (0, 1, 7) else None, category, text,
               f"b-{i - 1:010d}" if kind in (1, 3) else None)


def matches(row, filters):
    return (filters.get("date_from", FIRST) <= row.day <= filters.get("date_to", LAST)
            and ("portfolio_id" not in filters or filters["portfolio_id"] == f"p-{row.portfolio}")
            and ("property_id" not in filters or filters["property_id"] == row.effective_property)
            and ("unit_id" not in filters or filters["unit_id"] == row.unit))


@dataclass
class Totals:
    total: int = 0
    income: int = 0
    expense: int = 0
    categories: dict = field(default_factory=lambda: defaultdict(int))
    monthly: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    receivables: int = 0
    credits: int = 0

    def add(self, row):
        self.total += row.amount
        self.categories[row.category] += row.amount
        if row.side == "income":
            self.income += row.amount
            self.monthly[row.day[:7]][0] += row.amount
        else:
            self.expense -= row.amount
            self.monthly[row.day[:7]][1] -= row.amount


class Oracle:
    """Small aggregates and first search pages, not a second copy of a million rows."""

    def __init__(self, rows):
        self.rows = rows
        self.totals = {name: Totals() for name in FILTERS}
        self.accounts = defaultdict(int)
        self.search = {(q, p): {"count": 0, "first": [], "sha256": hashlib.sha256()}
                       for q in SEARCH_QUERIES for p in (None, 0)}

    def add(self, row, *, search=True):
        for name, filters in FILTERS.items():
            if matches(row, filters):
                self.totals[name].add(row)
        self.accounts[row.account] += row.amount
        if search:
            for (q, p), result in self.search.items():
                if (p is None or p == row.portfolio) and q.lower() in row.text.lower():
                    result["count"] += 1
                    if len(result["first"]) < 300:
                        result["first"].append(row.id)
                    result["sha256"].update((row.id + "\n").encode())


def insert(connection, table, records):
    if not records:
        return
    keys = list(records[0])
    sql = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
    connection.executemany(sql, [tuple(row[k] for k in keys) for row in records])


def seed(path, rows, checkpoint, guard, *, receivables=True):
    oracle = Oracle(rows)
    timestamps = {"created_at": STAMP, "updated_at": STAMP}
    with closing(sqlite3.connect(path, timeout=30)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        insert(db, "portfolios", [{"id": f"p-{p}", "name": f"Synthetic portfolio {p}", "currency": "EUR",
                                   "timezone": "Europe/Berlin", "status": "active", **timestamps} for p in range(3)])
        insert(db, "accounts", [{"id": f"acc-{a}", "portfolio_id": f"p-{a % 3}", "name": f"Synthetic account {a}",
                                 "account_type": "bank", "opening_balance": "100.00", "balance": "100.00",
                                 **timestamps} for a in range(6)])
        insert(db, "categories", [{"id": f"cat-{p}-{side}", "portfolio_id": f"p-{p}", "name": f"{p} {side}",
                                   "category_type": side, **timestamps} for p in range(3) for side in ("income", "expense")])
        insert(db, "properties", [{"id": f"prop-{p:02d}", "portfolio_id": f"p-{p % 3}",
                                   "name": f"Synthetic property {p}", "property_type": "residential", "status": "active",
                                   **timestamps} for p in range(30)])
        insert(db, "units", [{"id": f"unit-{u:03d}", "property_id": f"prop-{u % 30:02d}", "label": f"Unit {u}",
                              "unit_type": "residential", "status": "occupied", "cold_rent": "600.00",
                              "service_charge_advance": "150.00", "heating_advance": "50.00", **timestamps}
                             for u in range(300)])
        insert(db, "tenants", [{"id": f"tenant-{u:03d}", "full_name": f"Synthetic tenant {u}", "archived": 0,
                                **timestamps} for u in range(300)])
        insert(db, "contracts", [{"id": f"contract-{u:03d}", "contract_number": f"SYNTH-{u:03d}",
                                  "property_id": f"prop-{u % 30:02d}", "unit_id": f"unit-{u:03d}",
                                  "tenant_id": f"tenant-{u:03d}", "start_date": FIRST, "status": "active",
                                  **timestamps} for u in range(300)])
        insert(db, "contract_rent_periods", [{"id": f"rent-{u:03d}", "contract_id": f"contract-{u:03d}",
                                              "valid_from": FIRST, "cold_rent": "600.00",
                                              "service_charge_advance": "150.00", "heating_advance": "50.00",
                                              "source": "manual", **timestamps} for u in range(300)])
        db.commit()
        for offset in range(0, rows, 2000):
            guard.check()
            batch = []
            for i in range(offset, min(offset + 2000, rows)):
                row = fixture_row(i, rows)
                oracle.add(row)
                batch.append({"id": row.id, "account_id": row.account, "category_id": row.category,
                              "property_id": row.property, "unit_id": row.unit, "tenant_id": row.tenant,
                              "booking_date": row.day, "amount": str(Decimal(row.amount) / 100), "status": "booked",
                              "payment_text": row.text, "reverses_booking_id": row.reverses, **timestamps})
            insert(db, "bookings", batch)
            db.commit()
            if offset % 100000 == 0:
                checkpoint("seed_progress", {"bookings": min(offset + 2000, rows)})
        if receivables:
            for month_index, month in enumerate(MONTHS):
                batch = []
                for u in range(300):
                    status = ("open", "paid", "partial", "overdue", "cancelled")[(u + month_index) % 5]
                    amount = -(1000 + u) if (u + month_index) % 17 == 0 else 80000 + u
                    row = Row("", month + "-03", amount, "income", u % 3, "", f"prop-{u % 30:02d}",
                              f"unit-{u:03d}", f"tenant-{u:03d}", None, "")
                    if status in ("open", "partial", "overdue"):
                        for name, filters in FILTERS.items():
                            if matches(row, filters):
                                if amount > 0:
                                    oracle.totals[name].receivables += amount
                                else:
                                    oracle.totals[name].credits -= amount
                    batch.append({"id": f"r-{month_index:03d}-{u:03d}", "contract_id": f"contract-{u:03d}",
                                  "due_date": row.day, "amount_due": str(Decimal(amount) / 100), "status": status,
                                  **timestamps})
                insert(db, "receivables", batch)
                db.commit()
        require(db.execute("PRAGMA foreign_key_check").fetchone() is None, "Fixture foreign keys invalid")
        actual = db.execute("SELECT count(*),sum(cast(round(amount*100) AS INTEGER)) FROM bookings").fetchone()
        require(actual == (rows, oracle.totals["all"].total), f"Seed count/cents differ: {actual}")
    return oracle


def source_identity():
    def git(*args):
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    return {"head": git("rev-parse", "HEAD"), "changed_paths": git("status", "--short").splitlines(),
            "sha256": {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in SOURCE_FILES}}


class Run:
    def __init__(self, args):
        self.args = args
        self.out = fresh_directory(args.out, f"rows-{args.rows}")
        self.server = ScaleServer(self.out, "server")
        self.guard = Monitor(self.server, self.out, memory_mib=args.memory_mib,
                             minimum_free_mib=args.minimum_free_mib, seconds=args.stage_seconds)
        self.clients = []
        self.lock = threading.RLock()
        self.events = []
        self.active_reads = self.active_writes = self.overlaps = 0
        self.max_inflight = 0
        self.data = {"status": "running", "rows": args.rows, "months": 240, "source": source_identity(),
                     "platform": platform.platform(), "python": sys.version, "sqlite": sqlite3.sqlite_version,
                     "logical_cpus": os.cpu_count(), "date": date.today().isoformat(),
                     "limits": {"request_seconds": args.request_seconds, "stage_seconds": args.stage_seconds,
                                "stage_scope": "overall_run", "memory_mib": args.memory_mib,
                                "minimum_free_mib": args.minimum_free_mib},
                     "mixed_seconds": args.mixed_seconds,
                     "coverage": {"finance": True, "cashflow": True, "search_keyword": True,
                                  "search_selected_export": True, "receivables": not args.no_receivables,
                                  "period_result": False, "forecast": False, "DATEV": False, "restart": False,
                                  "real_documents_OCR": False, "backup_restore": False, "PostgreSQL": False},
                     "notes": ["Synthetic bulk fixture, not a 20-year business workflow simulation.",
                               "Backend API timings; no browser rendering timing.",
                               "Full results of selected search terms exported; not a one-million-hit export.",
                               "Single local SQLite worker. All background schedulers and AI disabled.",
                               "Other workstation activity is not controlled; timing is host-specific."]}

    def save(self):
        with self.lock:
            payload = {**self.data, "resource_peaks": dict(self.guard.peaks), "request_count": len(self.events)}
            temporary = self.out / "report.json.tmp"
            with temporary.open("w", encoding="utf-8") as target:
                json.dump(payload, target, indent=2, ensure_ascii=False)
                target.flush()
                os.fsync(target.fileno())
            temporary.replace(self.out / "report.json")

    def checkpoint(self, label, value=None):
        with self.lock:
            self.data.setdefault("checkpoints", []).append({"label": label, "value": value})
            self.save()
        print(json.dumps({"stage": label, "value": value}, ensure_ascii=False), flush=True)

    def phase(self, label):
        self.guard.check()
        self.guard.phase = label
        self.checkpoint(label)

    def client(self, username, token=None):
        client = httpx.Client(base_url=self.server.base, timeout=self.args.request_seconds,
                              headers={"Authorization": f"Bearer {token}"} if token else None)
        self.clients.append(client)
        return username, client

    def call(self, client, method, path, *, params=None, payload=None, label=None, export=None, expect=200):
        self.guard.check()
        username, http = client
        write = method != "GET"
        started = time.perf_counter()
        event = {"user": username, "method": method, "path": path, "params": params, "label": label,
                 "phase": self.guard.phase}
        # HTTPX read timeouts reset between chunks. Also enforce a wall-clock
        # deadline: a slow/trickling request stops only this owned test server.
        complete, deadline_lock = threading.Event(), threading.Lock()

        def expire():
            with deadline_lock:
                if complete.is_set():
                    return
                event["deadline_exceeded"] = True
            self.guard.fail(f"HTTP deadline exceeded: {method} {path} ({self.args.request_seconds}s)")

        deadline = threading.Timer(self.args.request_seconds, expire)
        deadline.daemon = True
        deadline.start()
        with self.lock:
            self.active_writes += int(write)
            self.active_reads += int(not write)
            if self.active_reads and self.active_writes:
                self.overlaps += 1
            self.max_inflight = max(self.max_inflight, self.active_reads + self.active_writes)
        try:
            if export is not None:
                with http.stream(method, path, params=params) as response:
                    event["status"] = response.status_code
                    require(response.status_code == expect, f"{path}: HTTP {response.status_code}")
                    with export.open("wb") as target:
                        for chunk in response.iter_bytes():
                            self.guard.check()
                            target.write(chunk)
                self.guard.check()
                return None
            response = http.request(method, path, params=params, json=payload)
            event["status"] = response.status_code
            require(response.status_code == expect, f"{path}: HTTP {response.status_code}: {response.text[:250]}")
            self.guard.check()
            return response.json()
        except BaseException as exc:
            event["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            with deadline_lock:
                complete.set()
                deadline.cancel()
            deadline.join(timeout=15)
            event["seconds"] = round(time.perf_counter() - started, 6)
            with self.lock:
                self.active_writes -= int(write)
                self.active_reads -= int(not write)
                self.events.append(event)
                with (self.out / "requests.jsonl").open("a", encoding="utf-8") as target:
                    target.write(json.dumps(event, ensure_ascii=False) + "\n")

    def login(self, username):
        client = self.client(username)
        data = self.call(client, "POST", "/auth/login", payload={"username": username, "password": PASSWORD})
        client[1].headers["Authorization"] = f"Bearer {data['access_token']}"
        return client

    def setup(self):
        self.phase("startup")
        self.guard.start()
        self.server.start(timeout=45)
        anon = self.client("setup")
        self.call(anon, "POST", "/auth/register", payload={"username": "scaleowner", "email": "owner@scale.test",
                  "full_name": "Synthetic benchmark owner", "password": PASSWORD}, expect=201)
        self.owner = self.login("scaleowner")
        self.phase("seed")
        started = time.perf_counter()
        self.oracle = seed(self.server.db_file, self.args.rows, self.checkpoint, self.guard,
                           receivables=not self.args.no_receivables)
        self.data["seed_seconds"] = time.perf_counter() - started
        self.data["fixture_counts"] = {"bookings": self.args.rows, "receivables": 0 if self.args.no_receivables else 72000,
                                       "portfolios": 3, "properties": 30, "units": 300, "contracts": 300}
        self.users = []
        for index in range(10):
            restricted = index in (1, 3, 5, 7)
            username = f"scaleuser{index}"
            self.call(self.owner, "POST", "/auth/users", payload={"username": username,
                      "email": f"{username}@scale.test", "full_name": f"Synthetic user {index}", "password": PASSWORD,
                      "role": "buchhaltung" if index >= 8 else "readonly",
                      "portfolio_access": "selected" if restricted else "all",
                      "portfolio_ids": ["p-0"] if restricted else []}, expect=201)
            self.users.append(self.login(username))
        identities = [self.call(user, "GET", "/auth/me") for user in self.users]
        require(len({user["id"] for user in identities}) == 10, "Ten distinct authenticated users required")
        self.data["users"] = [{"username": user["username"], "role": user["role"],
                                "portfolio_access": user.get("portfolio_access")} for user in identities]
        self.checkpoint("seed_and_users_verified")

    def finance(self, body, expected):
        require(cents(body["bookingsTotal"]) == expected.total, "Finance total differs from independent integer ledger")
        require(cents(body["uncategorizedTotal"]) == expected.categories.get(None, 0), "Uncategorized total differs")
        actual = {row["categoryId"]: cents(row["total"]) for row in body["totalsByCategory"]}
        wanted = {key: value for key, value in expected.categories.items() if key is not None}
        require(actual == wanted, f"Category totals differ: {actual} != {wanted}")

    def cashflow(self, body, expected, filters):
        require((cents(body["incomeTotal"]), cents(body["expenseTotal"]), cents(body["netTotal"])) ==
                (expected.income, expected.expense, expected.total), "Cashflow total differs")
        wanted = [month for month in MONTHS if filters["date_from"][:7] <= month <= filters["date_to"][:7]]
        require([row["month"] for row in body["monthly"]] == wanted, "Cashflow months missing or duplicated")
        for row in body["monthly"]:
            income, expense = expected.monthly.get(row["month"], [0, 0])
            require((cents(row["income"]), cents(row["expense"]), cents(row["net"])) ==
                    (income, expense, income - expense), f"Cashflow month {row['month']} differs")

    def aggregates(self):
        self.phase("finance_and_cashflow")
        for name, filters in FILTERS.items():
            expected = self.oracle.totals[name]
            for temperature in ("first", "repeat"):
                self.finance(self.call(self.owner, "GET", "/reports/finance", params=filters,
                                       label=f"{name}:{temperature}"), expected)
                self.cashflow(self.call(self.owner, "GET", "/reports/cashflow", params=filters,
                                        label=f"{name}:{temperature}"), expected, filters)
        self.finance(self.call(self.users[1], "GET", "/reports/finance", params=FILTERS["all"], label="scoped"),
                     self.oracle.totals["portfolio"])
        self.phase("account_detail")
        for account in ("acc-0", "acc-1"):
            body = self.call(self.owner, "GET", f"/accounts/{account}")
            require(cents(body["balance"]) == 10000 + self.oracle.accounts[account], "Account balance differs")
        self.phase("receivable_reports")
        for name in ("all", "year", "unit"):
            expected = self.oracle.totals[name]
            body = self.call(self.owner, "GET", "/reports/summary", params=FILTERS[name], label=name)["finance"]
            require(cents(body["bookingsTotal"]) == expected.total, "Summary booking total differs")
            require(cents(body["invoicesTotal"]) == 0, "Unexpected invoice total")
            require(cents(body["openReceivables"]) == expected.receivables, "Summary receivables differ")
            require(cents(body["overdueReceivables"]) == expected.receivables, "Summary overdue total differs")
            require(cents(body["openCredits"]) == expected.credits, "Summary credits differ")
            aging = self.call(self.owner, "GET", "/reports/receivables-aging", params=FILTERS[name], label=name)
            require(cents(aging["openTotal"]) == expected.receivables, "Aging total differs")
            require(cents(aging["openCredits"]) == expected.credits, "Aging credits differ")
            require(cents(aging["buckets"]["days90plus"]) == expected.receivables, "Aging historical bucket differs")
        self.checkpoint("aggregate_oracles_passed")

    def search_page(self, client, query, portfolio=None, cursor=None, offset=0):
        parameters = {"q": query, "type": "booking", "semantic": "false", "limit": 100}
        if cursor:
            parameters["cursor"] = cursor
        body = self.call(client, "GET", "/search", params=parameters, label="restricted" if portfolio == 0 else "all")
        expected = self.oracle.search[(query, portfolio)]
        require(body["total"] == expected["count"], f"Search count differs for {query!r}")
        require([row["id"] for row in body["results"]] == expected["first"][offset:offset + 100], "Search page IDs differ")
        require(body["has_more"] == (expected["count"] > offset + 100), "Search has_more differs")
        return body

    def searches(self):
        self.phase("search")
        for query in SEARCH_QUERIES:
            self.search_page(self.owner, query)
        self.search_page(self.users[1], "synthetic booking", 0)
        body = self.search_page(self.owner, "export-bucket")
        for offset in (100, 200):
            if body["next_cursor"]:
                body = self.search_page(self.owner, "export-bucket", cursor=body["next_cursor"], offset=offset)
        overview = self.call(self.owner, "GET", "/search", params={"q": "tailmarker2026", "semantic": "false"})
        require([row["id"] for row in overview["results"]] == [f"b-{self.args.rows - 1:010d}"], "Overview tail hit differs")
        self.phase("search_export")
        for client, portfolio in ((self.owner, None), (self.users[1], 0)):
            target = self.out / f"search-export-{portfolio}.csv"
            self.call(client, "GET", "/search/export", params={"q": "export-bucket", "type": "booking"}, export=target)
            expected, digest, count = self.oracle.search[("export-bucket", portfolio)], hashlib.sha256(), 0
            with target.open(encoding="utf-8-sig", newline="") as source:
                for row in csv.DictReader(source, delimiter=";"):
                    require(row["entity_type"] == "booking", "Export type differs")
                    index = int(row["id"].split("-")[1])
                    require(0 <= index < self.args.rows, "Export ID outside fixture")
                    original = fixture_row(index, self.args.rows)
                    require(row["display"] == original.text, "Export content differs")
                    require(exported_cents(row["detail"]) == original.amount, "Export amount differs")
                    digest.update((row["id"] + "\n").encode())
                    count += 1
            require(count == expected["count"] and digest.hexdigest() == expected["sha256"].hexdigest(),
                    "Full export IDs/count differ, including ordering or duplicates")
            self.checkpoint("export_verified", {"portfolio": portfolio, "rows": count, "bytes": target.stat().st_size})
        self.phase("booking_pages")
        with closing(sqlite3.connect(self.server.db_file)) as db:
            count = db.execute("SELECT count(*) FROM bookings WHERE booking_date BETWEEN ? AND ?",
                               ("2016-01-01", "2016-12-31")).fetchone()[0]
            for offset in (0, max(0, count - 10)):
                expected = [row[0] for row in db.execute(
                    "SELECT id FROM bookings WHERE booking_date BETWEEN ? AND ? ORDER BY id LIMIT 10 OFFSET ?",
                    ("2016-01-01", "2016-12-31", offset))]
                body = self.call(self.owner, "GET", "/bookings", params={**FILTERS["year"], "skip": offset,
                                                                          "limit": 10, "sort_by": "id"})
                require([row["id"] for row in body] == expected, "Filtered booking tail/page differs")
        self.checkpoint("search_and_page_oracles_passed")

    def mixed(self):
        self.phase("mixed_ten_users")
        gate, stop = threading.Barrier(10), threading.Event()
        writes, failures = [], []
        started = time.perf_counter()
        deadline = started + self.args.mixed_seconds
        overlaps_before = self.overlaps

        def worker(index):
            client, iteration = self.users[index], 0
            gate.wait(timeout=15)
            try:
                while time.perf_counter() < deadline and not stop.is_set():
                    iteration += 1
                    if index < 4:
                        self.search_page(client, ("export-bucket", "ÖZTÜRK")[iteration % 2],
                                         0 if index % 2 else None)
                    elif index < 8:
                        # The historical year is immutable while new payments change December 2025.
                        filters = dict(FILTERS["year"])
                        if index % 2:
                            filters["portfolio_id"] = "p-0"
                        body = self.call(client, "GET", "/reports/cashflow", params=filters, label="stable_year")
                        if index % 2:
                            expected = Totals()
                            for month, values in self.oracle.totals["portfolio"].monthly.items():
                                if month.startswith("2016-"):
                                    expected.monthly[month] = values
                                    expected.income += values[0]
                                    expected.expense += values[1]
                            expected.total = expected.income - expected.expense
                        else:
                            expected = self.oracle.totals["year"]
                        self.cashflow(body, expected, filters)
                    elif iteration <= 20:
                        account = index - 8
                        amount = 100 + iteration
                        payload = {"account_id": f"acc-{account}", "category_id": f"cat-{account}-income",
                                   "booking_date": LAST, "amount": amount / 100,
                                   "payment_text": f"SCALE-WRITE-{index}-{iteration}", "status": "booked"}
                        body = self.call(client, "POST", "/bookings", payload=payload, expect=201)
                        with self.lock:
                            writes.append((body["id"], payload, amount))
                    else:
                        break
                    # Spread writers across the measurement window, instead of warming caches
                    # for a long read-only tail after every write has already finished.
                    stop.wait(max(0.15, self.args.mixed_seconds / 20) if index >= 8 else 0.15)
            except BaseException as exc:
                with self.lock:
                    failures.append(f"user{index}: {type(exc).__name__}: {exc}")
                stop.set()

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(worker, range(10)))
        self.data["mixed"] = {"seconds": time.perf_counter() - started, "writes_acknowledged": len(writes),
                              "read_write_overlap_events": self.overlaps - overlaps_before,
                              "max_simultaneous_requests": self.max_inflight, "failures": failures}
        self.save()
        require(not failures, f"Mixed workload failed: {failures}")
        require(len(writes) > 0 and self.overlaps > overlaps_before, "Mixed load did not overlap reads and writes")
        self.phase("post_write_verification")
        require(len({row[0] for row in writes}) == len(writes), "Duplicate acknowledged booking IDs")
        with closing(sqlite3.connect(self.server.db_file)) as db:
            require(db.execute("SELECT count(*) FROM bookings").fetchone()[0] == self.args.rows + len(writes),
                    "Booking count differs after writes")
            for booking_id, payload, amount in writes:
                persisted = db.execute("SELECT account_id,category_id,booking_date,amount,payment_text FROM bookings WHERE id=?",
                                       (booking_id,)).fetchone()
                require(persisted is not None and persisted[:3] == (payload["account_id"], payload["category_id"], LAST)
                        and cents(persisted[3]) == amount and persisted[4] == payload["payment_text"],
                        "Acknowledged write changed or missing")
                require(db.execute("SELECT count(*) FROM bookings WHERE payment_text=?", (payload["payment_text"],)).fetchone()[0] == 1,
                        "Acknowledged write stored more than once")
                portfolio = int(payload["account_id"].split("-")[1])
                self.oracle.add(Row(booking_id, LAST, amount, "income", portfolio, payload["account_id"], None, None, None,
                                    payload["category_id"], payload["payment_text"]), search=False)
        # No TTL sleep: confirmed writes must immediately invalidate cached reports.
        for client, name, filters in ((self.owner, "all", FILTERS["all"]),
                                      (self.users[1], "portfolio", FILTERS["all"])):
            self.finance(self.call(client, "GET", "/reports/finance", params=filters), self.oracle.totals[name])
            self.cashflow(self.call(client, "GET", "/reports/cashflow", params=filters), self.oracle.totals[name], filters)
        self.data["mixed"]["writes_verified"] = len(writes)
        self.checkpoint("mixed_and_write_oracles_passed", self.data["mixed"])

    def finish(self):
        try:
            self.server.stop()
        finally:
            try:
                self.guard.close()
            finally:
                for client in self.clients:
                    client.close()
        self.guard.check()

    def summarize(self):
        groups = defaultdict(list)
        for event in self.events:
            groups[event["phase"]].append(event["seconds"])
        self.data["latency_seconds"] = {
            phase: {"samples": len(values), "p50": sorted(values)[len(values) // 2],
                    "p95": sorted(values)[math.ceil(len(values) * .95) - 1], "max": max(values)}
            for phase, values in groups.items()}
        self.data["source_end"] = source_identity()
        self.data["source_changed_during_run"] = self.data["source"]["sha256"] != self.data["source_end"]["sha256"]
        self.data["database_bytes"] = self.server.db_file.stat().st_size if self.server.db_file.exists() else 0
        self.data["http_errors"] = [event for event in self.events if "error" in event]
        self.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--out", type=Path, default=REPO / "artifacts" / "scale-finance-search")
    parser.add_argument("--mixed-seconds", type=float, default=30)
    parser.add_argument("--request-seconds", type=float, default=30)
    parser.add_argument("--stage-seconds", type=float, default=600,
                        help="Overall run deadline, including startup, fixture generation and every phase")
    parser.add_argument("--memory-mib", type=int, default=2048)
    parser.add_argument("--minimum-free-mib", type=int, default=1024)
    parser.add_argument("--no-receivables", action="store_true", help="Isolate booking/search pressure; records this exclusion")
    args = parser.parse_args(argv)
    if args.rows < 1000 or args.rows % 10 or min(args.mixed_seconds, args.request_seconds, args.stage_seconds,
                                                args.memory_mib, args.minimum_free_mib) <= 0:
        parser.error("rows must be >=1000 and divisible by 10; resource/time limits must be positive")
    if date.today() <= date(2026, 4, 1):
        parser.error("Historical receivable aging oracle requires a date after 2026-04-01")
    run = Run(args)
    print(f"RESULT_DIR={run.out}", flush=True)
    started = time.perf_counter()
    run.save()
    try:
        run.setup()
        run.aggregates()
        run.searches()
        run.mixed()
        run.data["status"] = "passed"
    except BaseException as exc:
        run.data["status"] = "failed"
        run.data["error"] = f"{type(exc).__name__}: {exc}"
        (run.out / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(run.data["error"], flush=True)
    finally:
        try:
            run.finish()
            run.data["owned_processes_stopped"] = True
        except BaseException as exc:
            run.data["status"] = "failed"
            run.data["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        run.data["elapsed_seconds"] = time.perf_counter() - started
        run.summarize()
        print(f"RESULT={run.out / 'report.json'} STATUS={run.data['status']}", flush=True)
    return 0 if run.data["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
