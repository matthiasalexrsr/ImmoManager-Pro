"""Save and load: restart, hard kill during writes, export/import, backup/restore, migration, bad files.

Each check compares a fingerprint (counts and content hashes of every entity, tenant
accounts, current rents, review list) before and after. Checks that change data run on a
copy of the server so the simulation can continue on the original.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time

import httpx

from .core import REPO, Client, Findings, Server, setup_users
from .invariants import compare, fingerprint


def relogin(users: dict[str, Client]) -> None:
    for client in users.values():
        client.login()


def restart(server: Server, users: dict[str, Client], f: Findings) -> None:
    before = fingerprint(users["owner"])
    server.restart()
    relogin(users)
    compare(f, before, fingerprint(users["owner"]), "Neustart")


def hard_kill(server: Server, users: dict[str, Client], f: Findings, account_id: str) -> None:
    """Kill the server while bookings are being written; afterwards nothing may be half-saved."""
    server.stop()
    clone = server.clone("absturz")
    server.start()
    relogin(users)
    clone.start()
    client = setup_users(clone, f)["buchhaltung"]
    acknowledged: list[str] = []
    stop = threading.Event()

    def writer():
        # raw HTTP: connection errors are expected while the server dies
        http = httpx.Client(timeout=10)
        n = 0
        while not stop.is_set():
            n += 1
            try:
                resp = http.post(f"{clone.base}/bookings", headers={"Authorization": f"Bearer {client.token}"},
                                 json={"account_id": account_id, "booking_date": "2026-01-15", "amount": 10 + n,
                                       "payment_text": f"Absturztest {n}"})
            except httpx.HTTPError:
                return
            if resp.status_code in (200, 201):
                acknowledged.append(resp.json()["id"])

    thread = threading.Thread(target=writer)
    thread.start()
    time.sleep(1.5)
    clone.stop(hard=True)
    stop.set()
    thread.join(timeout=30)
    clone.start()
    owner = Client(clone, f, "owner")
    stored = {b["id"] for b in owner.all("/bookings", area="Absturz")}
    lost = [i for i in acknowledged if i not in stored]
    f.check(not lost, "KRITISCH", "Absturz", f"{len(lost)} bestätigte Buchungen nach hartem Absturz verloren")
    status, check = owner.call("GET", "/admin/integrity-check", area="Absturz")
    if status == 200 and isinstance(check, dict):
        problems = {k: v for k, v in check.items() if v and k not in ("status", "ok", "checked_at", "summary")}
        f.check(check.get("status", "ok") in ("ok", "healthy", True) or not problems, "KRITISCH", "Absturz",
                "Integritätsprüfung nach Absturz meldet Probleme", check)
    clone.stop()


def export_import(server: Server, users: dict[str, Client], f: Findings) -> None:
    owner = users["owner"]
    status, raw = owner.call("GET", "/data/export", raw=True, area="Export")
    if status != 200:
        return
    before = fingerprint(owner)
    fresh = Server(server.dir.parent, "import")
    if fresh.dir.exists():
        shutil.rmtree(fresh.dir)
        fresh.dir.mkdir(parents=True)
    fresh.start()
    try:
        target = setup_users(fresh, f)["owner"]
        status, _ = target.call("POST", "/data/import", files={"file": ("export.json", raw, "application/json")},
                                     area="Import")
        if status != 200:
            return
        after = fingerprint(target)
        compare(f, before, after, "Export → Import in neue Installation")
        # importing the same file again must not duplicate anything
        target.call("POST", "/data/import", files={"file": ("export.json", raw, "application/json")}, area="Import")
        again = fingerprint(target)
        f.check(again["counts"] == after["counts"], "KRITISCH", "Import",
                "Zweiter Import derselben Datei hat Datensätze verdoppelt",
                {k: (after["counts"].get(k), v) for k, v in again["counts"].items() if after["counts"].get(k) != v})
        bad_files(target, f, raw)
    finally:
        fresh.stop()


def bad_files(client: Client, f: Findings, raw: bytes) -> None:
    """Broken or foreign files must be refused as a whole; nothing may be half-imported."""
    data = json.loads(raw)
    before = fingerprint(client)["counts"]
    first_contract = (data.get("contracts") or [{}])[0]
    cases = {
        "abgeschnitten": raw[: len(raw) // 2],
        "kein JSON": b"Mieterliste\nMueller;800\n",
        "falsches Format": json.dumps({"format": "other-app", "tenants": []}).encode(),
        "künftige Version": json.dumps({**data, "format_version": 99}).encode(),
        "Vertrag zu fehlender Einheit": json.dumps({**data, "contracts": [{**first_contract, "id": "c-x" * 6,
                                                                          "unit_id": "fehlt"}]}).encode(),
        "Buchung mit Text als Betrag": json.dumps({**data, "bookings": [{**(data.get("bookings") or [{}])[0],
                                                                         "id": "b-x" * 6, "amount": "zwölf"}]}).encode(),
        "leere Datei": b"",
    }
    for name, content in cases.items():
        status, body = client.call("POST", "/data/import", files={"file": ("x.json", content, "application/json")},
                                   expect=tuple(range(200, 500)), area="Import")
        if status and status < 400:
            f.add("LÜCKE", "Import", f"Datei „{name}“ wird ohne Fehlermeldung angenommen", body)
        after = fingerprint(client)["counts"]
        f.check(after == before, "KRITISCH", "Import", f"Fehlerhafte Datei „{name}“ hat Daten teilweise importiert",
                {k: (before.get(k), v) for k, v in after.items() if before.get(k) != v})


def backup_restore(server: Server, users: dict[str, Client], f: Findings) -> None:
    server.stop()
    clone = server.clone("backup")
    server.start()
    relogin(users)
    clone.start()
    try:
        owner = Client(clone, f, "owner")
        before = fingerprint(owner)
        backup = owner.ok("POST", "/admin/backup", {}, area="Backup")
        if not backup:
            return
        # change something, then go back
        tenants = owner.all("/tenants", area="Backup")
        if tenants:
            owner.call("PATCH", f"/tenants/{tenants[0]['id']}", {"full_name": "Geändert nach Backup"}, area="Backup")
        owner.call("POST", f"/admin/restore/{backup['backup']}", {}, area="Restore")
        owner.login()
        compare(f, before, fingerprint(owner), "Backup → Änderung → Restore")
        owner.call("POST", "/admin/restore/..%2F..%2Fetc%2Fpasswd", {}, expect=(400, 404, 405, 422), area="Restore")
    finally:
        clone.stop()


def migration(server: Server, users: dict[str, Client], f: Findings) -> None:
    """The schema migration must be a no-op on a current database and keep all data."""
    server.stop()
    clone = server.clone("migration")
    server.start()
    relogin(users)
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(REPO / "alembic.ini"), "upgrade", "head"],
                            cwd=REPO, env=clone.env(), capture_output=True, text=True, timeout=300)
    f.check(result.returncode == 0, "KRITISCH", "Migration", "alembic upgrade head schlägt fehl", result.stderr[-600:])
    clone.start()
    try:
        compare(f, fingerprint(users["owner"]), fingerprint(Client(clone, f, "owner")), "Migration auf Kopie")
    finally:
        clone.stop()


def checkpoint(server: Server, users: dict[str, Client], f: Findings, account_id: str, full: bool) -> None:
    previous = f.phase
    f.phase = f"speichern/laden ({previous})"
    restart(server, users, f)
    export_import(server, users, f)
    if full:
        backup_restore(server, users, f)
        migration(server, users, f)
        hard_kill(server, users, f, account_id)
    f.phase = previous
