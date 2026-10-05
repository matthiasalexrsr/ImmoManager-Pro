"""Extreme stress test: test server, API clients per user, findings and report.

Every finding has a class:
  KRITISCH  server error (5xx), crash, data loss or corruption after save/load
  FALSCH    a result differs from what the independent calculation expects
  LÜCKE     an implausible or invalid input is accepted without rejection or warning,
            or something a property manager needs is missing
  RECHTE    a role can do something it should not (or cannot do what it should)
  LANGSAM   a call took longer than the limit
  HINWEIS   worth a look, not wrong by itself
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
SEVERITIES = ["KRITISCH", "FALSCH", "LÜCKE", "RECHTE", "LANGSAM", "HINWEIS"]
SLOW_SECONDS = 2.0
PASSWORD = "Stress-Test-2026!"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    """A real app process (uvicorn, SQLite file) that can be stopped, restarted and copied."""

    def __init__(self, workdir: Path, name: str = "main", port: int | None = None):
        self.dir = workdir / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.port = port or free_port()
        self.proc: subprocess.Popen | None = None
        self.log = self.dir / "server.log"

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"

    @property
    def db_file(self) -> Path:
        return self.dir / "app.db"

    def env(self) -> dict:
        return {**os.environ,
                "DATA_DIR": str(self.dir), "DATABASE_URL": f"sqlite:///{self.db_file}",
                "JWT_SECRET_KEY": "x" * 48, "ENVIRONMENT": "production",
                "RATE_LIMIT_ENABLED": "false", "AUTO_SEED_DEMO_DATA": "false"}

    def start(self, timeout: float = 60) -> None:
        log = open(self.log, "a")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app:app", "--app-dir", str(REPO),
             "--port", str(self.port), "--log-level", "warning"],
            cwd=self.dir, env=self.env(), stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if httpx.get(f"{self.base}/auth/registration-status", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"server {self.dir.name} exited, see {self.log}")
            time.sleep(0.3)
        raise RuntimeError(f"server {self.dir.name} did not start, see {self.log}")

    def stop(self, hard: bool = False) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL if hard else signal.SIGTERM)
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def restart(self, hard: bool = False) -> None:
        self.stop(hard=hard)
        self.start()

    def clone(self, name: str) -> "Server":
        """A second server on a copy of this one's data (taken while it is stopped)."""
        other = Server(self.dir.parent, name)
        if other.dir.exists():
            shutil.rmtree(other.dir)
        shutil.copytree(self.dir, other.dir, ignore=shutil.ignore_patterns("server.log"))
        return other


class Findings:
    def __init__(self):
        self.items: list[dict] = []
        self.lock = threading.Lock()
        self.phase = "-"
        self.timings: list[tuple[str, str, float]] = []
        self.calls = Counter()

    def add(self, severity: str, area: str, message: str, detail: Any = None) -> None:
        assert severity in SEVERITIES, severity
        entry = {"phase": self.phase, "severity": severity, "area": area, "message": message,
                 "detail": json.dumps(detail, default=str, ensure_ascii=False)[:800] if detail is not None else None}
        with self.lock:
            self.items.append(entry)
        print(f"  !! [{severity}] {area}: {message}" + (f" | {entry['detail'][:240]}" if entry["detail"] else ""),
              flush=True)

    def check(self, condition: bool, severity: str, area: str, message: str, detail: Any = None) -> bool:
        if not condition:
            self.add(severity, area, message, detail)
        return bool(condition)

    def summary(self) -> dict:
        grouped = defaultdict(list)
        for item in self.items:
            grouped[item["severity"]].append(item)
        return grouped


class Client:
    """One logged-in user. Every call is timed; 5xx is always KRITISCH."""

    def __init__(self, server: Server, findings: Findings, username: str, password: str = PASSWORD):
        self.server, self.f, self.username = server, findings, username
        self.http = httpx.Client(timeout=180)
        self.token = None
        self.login(password)

    def login(self, password: str = PASSWORD) -> None:
        resp = self.http.post(f"{self.server.base}/auth/login", json={"username": self.username, "password": password})
        if resp.status_code != 200:
            raise RuntimeError(f"login {self.username}: {resp.status_code} {resp.text[:200]}")
        self.token = resp.json()["access_token"]

    def call(self, method: str, path: str, body: Any = None, *, expect=(200, 201, 204), area: str = "API",
             params: dict | None = None, files=None, quiet: bool = False, raw: bool = False):
        url = self.server.base + path
        started = time.perf_counter()
        try:
            resp = self.http.request(method, url, json=body, params=params, files=files,
                                     headers={"Authorization": f"Bearer {self.token}"})
        except httpx.HTTPError as exc:
            self.f.add("KRITISCH", area, f"{method} {path}: keine Antwort ({type(exc).__name__})", str(exc))
            return None, None
        elapsed = time.perf_counter() - started
        key = path.split("?")[0]
        for part in key.split("/"):
            if len(part) == 36 and part.count("-") == 4:
                key = key.replace(part, "{id}")
        with self.f.lock:
            self.f.timings.append((method, key, elapsed))
            self.f.calls[f"{self.username}"] += 1
        if resp.status_code == 401 and not quiet:
            self.login()
            return self.call(method, path, body, expect=expect, area=area, params=params, files=files, quiet=True,
                             raw=raw)
        if elapsed > SLOW_SECONDS:
            self.f.add("LANGSAM", area, f"{method} {key} dauerte {elapsed:.1f} s")
        content: Any = resp.content if raw else _json(resp)
        if resp.status_code >= 500:
            self.f.add("KRITISCH", area, f"{method} {path} -> {resp.status_code}", content if not raw else None)
        elif resp.status_code not in expect and not quiet:
            self.f.add("FALSCH", area, f"{method} {path} -> {resp.status_code} (erwartet {expect})", content)
        return resp.status_code, content

    def ok(self, method: str, path: str, body: Any = None, **kw):
        status, content = self.call(method, path, body, **kw)
        return content if status in (200, 201, 204) else None

    def all(self, path: str, **kw) -> list:
        sep = "&" if "?" in path else "?"
        rows, skip = [], 0
        while True:
            page = self.ok("GET", f"{path}{sep}skip={skip}&limit=1000", **kw) or []
            if not isinstance(page, list):
                return rows
            rows += page
            if len(page) < 1000:
                return rows
            skip += 1000


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:500]


USERS = [  # username, role, full name
    ("owner", "eigentuemer", "Petra Eigner"),
    ("verwalter", "verwalter", "Viktor Verwalter"),
    ("buchhaltung", "buchhaltung", "Berta Buchhalter"),
    ("hausmeister", "techniker", "Hans Hausmeister"),
    ("steuerberater", "readonly", "Stefan Steuer"),
]


def setup_users(server: Server, findings: Findings) -> dict[str, Client]:
    http = httpx.Client(timeout=60)
    status = http.get(f"{server.base}/auth/registration-status").json()
    if status.get("initial_setup"):
        http.post(f"{server.base}/auth/register", json={"username": "owner", "email": "owner@stress.test",
                                                        "full_name": "Petra Eigner", "password": PASSWORD})
    owner = Client(server, findings, "owner")
    for username, role, name in USERS[1:]:
        owner.call("POST", "/auth/users", {"username": username, "email": f"{username}@stress.test",
                                           "full_name": name, "password": PASSWORD, "role": role},
                   expect=(201, 409), area="Benutzer")
    return {username: (owner if username == "owner" else Client(server, findings, username))
            for username, _, _ in USERS}


def write_report(findings: Findings, out: Path, meta: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / "findings.json").write_text(json.dumps(findings.items, indent=1, ensure_ascii=False))
    grouped = findings.summary()
    slow = defaultdict(list)
    for method, path, seconds in findings.timings:
        slow[f"{method} {path}"].append(seconds)
    top = sorted(((max(v), sum(v) / len(v), len(v), k) for k, v in slow.items()), reverse=True)[:15]
    lines = ["# Extrem-Stresstest – Ergebnis", "",
             f"- Lauf: {meta.get('started')} · Dauer {meta.get('minutes', 0):.0f} min · "
             f"Seed {meta.get('seed')} · {meta.get('units')} Einheiten · {meta.get('years')} Jahre",
             f"- API-Aufrufe: {len(findings.timings)} ({', '.join(f'{u}: {n}' for u, n in findings.calls.items())})",
             "- Befunde: " + ", ".join(f"{s} {len(grouped.get(s, []))}" for s in SEVERITIES), ""]
    for severity in SEVERITIES:
        items = grouped.get(severity, [])
        if not items:
            continue
        lines += [f"## {severity} ({len(items)})", ""]
        seen = Counter()
        for item in items:
            key = (item["area"], item["message"])
            seen[key] += 1
            if seen[key] == 1:
                lines.append(f"- **{item['area']}** ({item['phase']}): {item['message']}"
                             + (f"  \n  `{item['detail'][:300]}`" if item["detail"] else ""))
        repeated = [(k, n) for k, n in seen.items() if n > 1]
        if repeated:
            lines.append("")
            lines += [f"- ↑ {n}× insgesamt: {k[1]}" for k, n in repeated]
        lines.append("")
    lines += ["## Langsamste Aufrufe", "", "| Aufruf | max s | Ø s | Anzahl |", "|---|---:|---:|---:|"]
    lines += [f"| {k} | {mx:.2f} | {avg:.2f} | {n} |" for mx, avg, n, k in top]
    path = out / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
