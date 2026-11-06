"""Save and load: restart, hard kill during writes, export/import, backup/restore, migration, bad files.

Each check compares a fingerprint (counts and content hashes of every entity, tenant
accounts, current rents, review list) before and after. Checks that change data run on a
copy of the server so the simulation can continue on the original.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from .core import REPO, Client, Findings, Server, setup_users
from .invariants import compare, counts, fingerprint


def relogin(users: dict[str, Client]) -> None:
    for client in users.values():
        client.login()


def bulk_operation(owner: Client, f: Findings, path: str, area: str):
    """Measure real interactive reads while a named synchronous archive call runs.

    Separate HTTP clients reuse the existing token, so measuring does not create
    authentication records or change the before/after persistence fingerprint.
    The normal Client policy still applies to every reader, including its 2s budget.
    """
    if path not in ('/admin/operations/backup', '/admin/operations/restore-probe'):
        raise ValueError('Only the two declared synchronous archive operations are supported')
    begin, finished = threading.Event(), threading.Event()
    readers, threads, rows = [], [], []
    root_url = owner.server.base.removesuffix('/api/v1')

    def read(client, endpoint):
        begin.wait()
        try:
            while not finished.is_set():
                started = time.perf_counter()
                status, _ = client.call('GET', endpoint, area='Lesbarkeit während Vollsicherung', quiet=True)
                ended = time.perf_counter()
                f.check(status == 200, 'FALSCH', 'Lesbarkeit während Vollsicherung',
                        f'GET {endpoint} war während einer Archivoperation nicht erfolgreich', status)
                with f.lock:
                    rows.append({'path': endpoint, 'status': status, 'started': started, 'ended': ended,
                                 'seconds': ended - started})
                finished.wait(.025)
        except Exception as error:
            f.add('KRITISCH', 'Lesbarkeit während Vollsicherung',
                  f'GET {endpoint}: Messung abgebrochen ({type(error).__name__})', str(error))

    try:
        for endpoint, base in [('/health', root_url), ('/tasks?limit=1', owner.server.base)]:
            client = object.__new__(Client)
            client.server, client.f = SimpleNamespace(base=base), f
            client.username, client.token = owner.username, owner.token
            client.http = httpx.Client(timeout=180, trust_env=False)
            readers.append(client)
            thread = threading.Thread(target=read, args=(client, endpoint), daemon=True)
            threads.append(thread)
            thread.start()
        started = time.perf_counter()
        begin.set()
        try:
            result = owner.ok('POST', path, {}, area=area)
        finally:
            ended = time.perf_counter()
            finished.set()
            for thread in threads:
                thread.join(timeout=185)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError('Archive responsiveness reader did not finish within the HTTP timeout')
        for row in rows:
            row['overlapped_bulk'] = row['started'] < ended and row['ended'] > started
            row['started_after_bulk_begin'] = row['started'] >= started
        overlap = [row for row in rows if row['overlapped_bulk'] and row['started_after_bulk_begin']]
        measurement = {'method': 'POST', 'path': path, 'seconds': ended - started,
                       'reader_calls': rows, 'overlapping_reader_calls': len(overlap),
                       'overlap_by_path': {p: sum(row['path'] == p for row in overlap)
                                           for p in ['/health', '/tasks?limit=1']},
                       'interactive_budget_seconds': 2.0}
        f.measurements.setdefault('bulk_responsiveness', []).append(measurement)
        if not all(measurement['overlap_by_path'].values()):
            f.add('HINWEIS', 'Lesbarkeit während Vollsicherung',
                  'Zeitüberschneidung nicht für beide Leser belegt; keine Responsivitätsabnahme', measurement)
        return result
    finally:
        finished.set()
        begin.set()
        for client in readers:
            client.http.close()


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
    stop = threading.Event()
    thread, owner, clone_users = None, None, {}
    try:
        clone_users = setup_users(clone, f)
        client = clone_users["buchhaltung"]
        acknowledged: list[str] = []

        def writer():
            # Raw HTTP: connection errors are expected while the server dies.
            with httpx.Client(timeout=10) as http:
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
        if thread.is_alive():
            raise RuntimeError("Crash-test writer did not stop")
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
    finally:
        stop.set()
        clone.stop(hard=True)
        if thread is not None:
            thread.join(timeout=15)
        for client in clone_users.values():
            client.http.close()
        if owner is not None:
            owner.http.close()


def export_import(server: Server, users: dict[str, Client], f: Findings) -> None:
    owner = users["owner"]
    status, raw = owner.call("GET", "/data/export", raw=True, expect=(200, 409), area="Export")
    if status == 409:
        # Private evidence requires the full archive. Accept only the specific
        # documented guard, then exercise its supported replacement explicitly.
        error = json.loads(raw).get('error', {}).get('message', '')
        if not f.check('vollständige Sicherung' in error and 'JSON' in error, 'FALSCH', 'Export',
                       'Unerwarteter Exportkonflikt statt Vollbackup-Hinweis', error):
            return
        before = fingerprint(owner)
        backup = bulk_operation(owner, f, '/admin/operations/backup', 'Vollsicherung')
        probe = bulk_operation(owner, f, '/admin/operations/restore-probe', 'Vollsicherung prüfen') if backup else None
        f.check(bool(probe and probe.get('ok') and probe.get('readiness') == 'data_verified'),
                'KRITISCH', 'Vollsicherung', 'Bank-/Schnittstellenbestand nicht vollständig wiederherstellbar', probe)
        compare(f, before, fingerprint(owner), 'Vollsicherung und isolierte Wiederherstellungsprobe')
        return
    if status != 200:
        return
    before = fingerprint(owner)
    fresh = Server(server.dir.parent, "import")
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
    before = counts(client)
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
        after = counts(client)
        f.check(after == before, "KRITISCH", "Import", f"Fehlerhafte Datei „{name}“ hat Daten teilweise importiert",
                {k: (before.get(k), v) for k, v in after.items() if before.get(k) != v})


def backup_restore(server: Server, users: dict[str, Client], f: Findings) -> None:
    server.stop()
    clone = server.clone("backup")
    server.start()
    relogin(users)
    clone.start()
    restored = None
    owner = restored_owner = None
    try:
        owner = Client(clone, f, "owner")
        original_token = owner.token
        before = fingerprint(owner)
        raw_backup = owner.ok("POST", "/admin/backup", {}, area="Backup-Sperrprobe")
        if not raw_backup:
            return
        owner.call("POST", f"/admin/restore/{raw_backup['backup']}", {}, expect=(409,), area="Live-Restore-Sperre")
        owner.call("POST", "/admin/restore/..%2F..%2Fetc%2Fpasswd", {},
                   expect=(400, 404, 405, 422), area="Restore-Pfadgrenze")
        compare(f, before, fingerprint(owner), "Abgewiesener Live-RawDB-Restore")
        backup = bulk_operation(owner, f, '/admin/operations/backup', 'Vollbackup vor Offline-Restore')
        if not backup:
            return
        archive_name = backup.get('archive', '')
        if not f.check(bool(archive_name) and Path(archive_name).name == archive_name,
                       'KRITISCH', 'Offline-Restore', 'Vollbackup liefert keinen sicheren Archivnamen'):
            return
        archive = clone.dir / 'backups/full' / archive_name
        # Change only the throwaway source copy. The restored NEW profile must
        # have the original archived contents; the source copy stays changed.
        tenants = owner.all("/tenants", area="Backup")
        if tenants:
            owner.call("PATCH", f"/tenants/{tenants[0]['id']}", {"full_name": "Geändert nach Backup"}, area="Backup")
        changed = fingerprint(owner)
        clone.stop()
        restored = Server(server.dir.parent, 'offline-restore', database_name='immo_manager.db')
        restored.secret = clone.secret
        output = restored.dir
        target = output / 'installation'
        restore_env = clone.env()
        restore_env['XSTRESS_RESTORE_PASSPHRASE'] = clone.secret
        command = [sys.executable, '-m', 'backend.ops', 'restore', str(archive), '--target', str(target),
                   '--passphrase-env', 'XSTRESS_RESTORE_PASSPHRASE']
        result = subprocess.run(command, cwd=clone.dir, env=restore_env, capture_output=True, timeout=180,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (output / 'restore-cli.stdout.log').write_bytes(result.stdout)
        (output / 'restore-cli.stderr.log').write_bytes(result.stderr)
        if not f.check(result.returncode == 0, 'KRITISCH', 'Offline-Restore',
                       'Vollarchiv konnte nicht offline in einen NEUEN Ordner wiederhergestellt werden',
                       {'exit_code': result.returncode, 'stderr': result.stderr[-800:].decode('utf-8', 'replace')}):
            return
        receipt = json.loads(result.stdout)
        if not f.check(receipt.get('dialect') == 'sqlite' and receipt.get('readiness') == 'data_verified',
                       'KRITISCH', 'Offline-Restore', 'Unvollständiger Offline-Wiederherstellungsnachweis', receipt):
            return
        sessions = receipt.get('sessions', {})
        closed = sessions.get('restored_sessions_closed')
        if not f.check(sessions.get('generation') == 'renewed' and type(closed) is int and closed >= 1,
                       'RECHTE', 'Offline-Restore', 'Archivsitzungen wurden nicht nachweisbar geschlossen', sessions):
            return
        restored.dir, restored.log = target, target / 'server.log'
        (target / '.xstress-owned.json').write_text(json.dumps({'kind': 'synthetic-xstress',
            'parent': str(target.parent), 'pid': os.getpid(),
            'database_name': 'immo_manager.db'}), encoding='utf-8')
        upgrade = subprocess.run([sys.executable, '-m', 'backend.upgrade'], cwd=target, env=restored.env(),
            capture_output=True, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (output / 'upgrade-cli.stdout.log').write_bytes(upgrade.stdout)
        (output / 'upgrade-cli.stderr.log').write_bytes(upgrade.stderr)
        if not f.check(upgrade.returncode == 0, 'KRITISCH', 'Offline-Restore',
                       'Explizites Upgrade des neuen Restoreprofils fehlgeschlagen',
                       {'exit_code': upgrade.returncode, 'stderr': upgrade.stderr[-800:].decode('utf-8', 'replace')}):
            return
        restored.start()
        restored_owner = Client(restored, f, 'owner')
        old_session = object.__new__(Client)
        old_session.server, old_session.f = restored, f
        old_session.username, old_session.token, old_session.http = 'owner-before-restore', original_token, restored_owner.http
        old_status, _ = old_session.call('GET', '/auth/me', expect=(401,), quiet=True,
                                        area='Restore-Sitzungssperre')
        f.check(old_status == 401, 'RECHTE', 'Offline-Restore',
                'Sitzung aus dem Quellprofil wurde im neuen Restoreprofil angenommen', old_status)
        compare(f, before, fingerprint(restored_owner), 'Vollarchiv → Offline-Neuprofil → Upgrade → HTTP')
        privacy = restored_owner.ok('GET', '/privacy/restore-review', area='Restore-Datenschutzsperre')
        f.check(bool(privacy and privacy.get('pending') is True), 'RECHTE', 'Offline-Restore',
                'Neues Restoreprofil muss bis zur ausdrücklichen Datenschutzprüfung gesperrt bleiben', privacy)
        clone.start()
        owner.login()
        compare(f, changed, fingerprint(owner), 'Offline-Restore lässt Quellprofil unverändert')
        f.measurements.setdefault('offline_restore', []).append({'cli_exit': result.returncode,
            'upgrade_exit': upgrade.returncode, 'readiness': receipt.get('readiness'),
            'new_profile_http_login': True, 'privacy_review_pending': bool(privacy and privacy.get('pending')),
            'database_name': restored.database_name, 'source_stopped_before_restore': True,
            'target_was_new': True, 'old_source_token_rejected': old_status == 401,
            'restored_sessions_closed': closed})
    finally:
        clone.stop()
        if restored is not None:
            restored.stop()
        for client in (owner, restored_owner):
            if client is not None:
                client.http.close()


def migration(server: Server, users: dict[str, Client], f: Findings) -> None:
    """The schema migration must be a no-op on a current database and keep all data."""
    server.stop()
    clone = server.clone("migration")
    server.start()
    relogin(users)
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(REPO / "alembic.ini"), "upgrade", "head"],
                            cwd=REPO, env=clone.env(), capture_output=True, text=True, timeout=300,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
