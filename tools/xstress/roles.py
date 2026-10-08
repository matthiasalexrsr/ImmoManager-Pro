"""Phase 4: who may do what, and what happens when several people work at the same time.

Runs on a copy of the simulated data. The role matrix states what a property management
office would expect; the app may be stricter, but it may not be more permissive.
"""

from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

from .core import PASSWORD, Client, Findings, Server, setup_users

SPARE_YEAR = date.today().year + 2     # test contracts in the future, but not implausibly far

# action -> roles that should be allowed to do it
MATRIX = {
    "Buchung anlegen": {"eigentuemer", "verwalter", "buchhaltung"},
    "Buchung löschen": {"eigentuemer", "verwalter", "buchhaltung"},
    "Zahlung aufteilen": {"eigentuemer", "verwalter", "buchhaltung"},
    "Vertrag anlegen": {"eigentuemer", "verwalter"},
    "Vertrag löschen": {"eigentuemer", "verwalter"},
    "Mietanpassung anwenden": {"eigentuemer", "verwalter"},
    "Mieter löschen": {"eigentuemer", "verwalter"},
    "Kaution ändern": {"eigentuemer", "verwalter", "buchhaltung"},
    "Wartungsfall anlegen": {"eigentuemer", "verwalter", "techniker"},
    "Zählerstand erfassen": {"eigentuemer", "verwalter", "techniker"},
    "Daten exportieren": {"eigentuemer", "verwalter"},
    "Backup wiederherstellen": {"eigentuemer"},
    "Benutzer anlegen (Verwalter-Rolle)": {"eigentuemer"},
    "Berichte lesen": {"eigentuemer", "verwalter", "buchhaltung", "techniker", "readonly"},
}
ROLE_OF = {"owner": "eigentuemer", "verwalter": "verwalter", "buchhaltung": "buchhaltung",
           "hausmeister": "techniker", "steuerberater": "readonly"}


def _actions(c: Client, refs: dict, username: str) -> dict:
    n = int(time.time() * 1000) % 100000
    booking = refs["booking"]
    return {
        "Buchung anlegen": ("POST", "/bookings", {"account_id": refs["account"], "booking_date": "2026-05-01", "amount": 1.0}),
        "Buchung löschen": ("DELETE", f"/bookings/{refs['spare_bookings'][username]}", None),
        "Zahlung aufteilen": ("PUT", f"/bookings/{booking['id']}/allocations", []),
        "Vertrag anlegen": ("POST", "/contracts", {"contract_number": f"R-{username}-{n}", "property_id": refs["free_unit"]["property_id"],
                                                   "unit_id": refs["free_unit"]["id"], "tenant_id": refs["tenant"],
                                                   "start_date": "2030-01-01", "status": "draft"}),
        "Vertrag löschen": ("DELETE", f"/contracts/{refs['spare_contracts'][username]}", None),
        "Mietanpassung anwenden": ("POST", f"/rent-adjustments/{refs['adjustments'][username]}/apply", {}),
        "Mieter löschen": ("DELETE", f"/tenants/{refs['spare_tenants'][username]}", None),
        "Kaution ändern": ("PATCH", f"/deposits/{refs['deposit']}", {"notes": f"geprüft von {username}"}),
        "Wartungsfall anlegen": ("POST", "/maintenance", {"property_id": refs["property"], "title": f"Test {username}"}),
        "Zählerstand erfassen": ("POST", f"/meters/{refs['meter']}/readings",
                                 {"meter_id": refs["meter"], "reading_date": "2026-09-30", "value": 99999 + n}),
        "Daten exportieren": ("GET", "/data/export", None),
        "Backup wiederherstellen": ("POST", "/admin/restore/backup_gibt_es_nicht.db", {}),
        "Benutzer anlegen (Verwalter-Rolle)": ("POST", "/auth/users", {"username": f"neu{username}{n}",
                                                                       "email": f"neu{username}{n}@stress.test",
                                                                       "full_name": "Neu", "password": PASSWORD,
                                                                       "role": "verwalter"}),
        "Berichte lesen": ("GET", "/reports/summary", None),
    }


def _prepare(users: dict[str, Client]) -> dict:
    v = users["verwalter"]
    contracts = v.all("/contracts")
    active = [x for x in contracts if x["status"] == "active"]
    units = v.all("/units")
    free = next((u for u in units if u["status"] == "vacant"), units[0])
    account = v.all("/accounts")[0]["id"]
    refs = {"account": account, "free_unit": free, "tenant": active[0]["tenant_id"], "property": active[0]["property_id"],
            "meter": (v.all("/meters") or [{"id": "x"}])[0]["id"], "deposit": (v.all("/deposits") or [{"id": "x"}])[0]["id"],
            "booking": v.ok("POST", "/bookings", {"account_id": account, "tenant_id": active[0]["tenant_id"],
                                                  "booking_date": "2026-05-02", "amount": 50.0}),
            "spare_bookings": {}, "spare_contracts": {}, "spare_tenants": {}, "adjustments": {}}
    for username in users:
        refs["spare_bookings"][username] = v.ok("POST", "/bookings", {"account_id": account, "booking_date": "2026-05-02",
                                                                      "amount": 2.0})["id"]
        tenant = v.ok("POST", "/tenants", {"full_name": f"Löschtest {username}"})
        refs["spare_tenants"][username] = tenant["id"]
        tenant2 = v.ok("POST", "/tenants", {"full_name": f"Vertragstest {username}"})
        spare = v.ok("POST", "/contracts", {"contract_number": f"DEL-{username}", "property_id": free["property_id"],
                                            "unit_id": free["id"], "tenant_id": tenant2["id"],
                                            # one month each, two years ahead (the app refuses more than 5)
                                            "start_date": f"{SPARE_YEAR}-{2 + list(users).index(username):02d}-01",
                                            "end_date": f"{SPARE_YEAR}-{2 + list(users).index(username):02d}-28",
                                            "status": "draft"})
        refs["spare_contracts"][username] = spare["id"] if spare else "x"
        target = active[list(users).index(username) % len(active)]
        periods = v.ok("GET", f"/contracts/{target['id']}/rent-periods") or [{"cold_rent": 500}]
        adj = v.ok("POST", "/rent-adjustments", {"contract_id": target["id"], "adjustment_type": "index",
                                                 "effective_date": "2027-02-01", "previous_rent": periods[-1]["cold_rent"],
                                                 "new_rent": round(periods[-1]["cold_rent"] * 1.02, 2)})
        refs["adjustments"][username] = adj["id"] if adj else "x"
    return refs


def matrix(users: dict[str, Client], f: Findings) -> None:
    refs = _prepare(users)
    table = []
    for username, client in users.items():
        role = ROLE_OF[username]
        for action, (method, path, body) in _actions(client, refs, username).items():
            status, _ = client.call(method, path, body, expect=tuple(range(200, 500)), area="Rechte")
            if status is None or status >= 500:
                continue
            allowed = status not in (401, 403)
            should = role in MATRIX[action]
            table.append((action, role, allowed))
            if allowed and not should:
                f.add("RECHTE", "Rechte", f"Rolle „{role}“ darf „{action}“ ({method} {path.split('?')[0]} → {status})")
            elif not allowed and should:
                f.add("RECHTE", "Rechte", f"Rolle „{role}“ darf „{action}“ nicht, sollte es aber ({status})")
    owner, verwalter = users["owner"], users["verwalter"]
    # nobody may raise their own role
    me = verwalter.ok("GET", "/auth/me", area="Rechte")
    status, _ = verwalter.call("PATCH", f"/auth/users/{me['id']}", {"role": "eigentuemer"}, expect=(400, 403, 404, 422),
                               area="Rechte")
    if status and status < 400:
        f.add("RECHTE", "Rechte", "Verwalter kann sich selbst zum Eigentümer machen")
    # a deactivated user is locked out at once, also with a token issued before
    target = users["hausmeister"]
    hid = target.ok("GET", "/auth/me", area="Rechte")["id"]
    owner.call("PATCH", f"/auth/users/{hid}", {"is_active": False}, area="Rechte")
    status, _ = target.call("GET", "/tenants", expect=(401, 403), area="Rechte", quiet=True)
    if status == 200:
        f.add("RECHTE", "Rechte", "Deaktivierter Benutzer kann mit altem Token weiterarbeiten")
    owner.call("PATCH", f"/auth/users/{hid}", {"is_active": True}, area="Rechte")
    # after a password reset the old password must no longer work
    owner.call("POST", f"/auth/users/{hid}/password", {"password": PASSWORD + "x"}, expect=(200, 204), area="Rechte")
    try:
        Client(target.server, f, "hausmeister", PASSWORD)
        f.add("RECHTE", "Rechte", "Altes Passwort funktioniert nach dem Zurücksetzen weiter")
    except RuntimeError:
        pass
    owner.call("POST", f"/auth/users/{hid}/password", {"password": PASSWORD}, expect=(200, 204), area="Rechte")
    # too many wrong passwords lock the account, but not the others
    import httpx
    for _ in range(7):
        httpx.post(f"{target.server.base}/auth/login", json={"username": "steuerberater", "password": "falsch"})
    locked = httpx.post(f"{target.server.base}/auth/login", json={"username": "steuerberater", "password": PASSWORD})
    f.check(locked.status_code in (401, 403, 423, 429), "RECHTE", "Anmeldung",
            "Nach 7 falschen Passwörtern ist das Konto nicht gesperrt")
    other = httpx.post(f"{target.server.base}/auth/login", json={"username": "buchhaltung", "password": PASSWORD})
    f.check(other.status_code == 200, "FALSCH", "Anmeldung", "Sperre eines Kontos sperrt auch andere Benutzer")


def concurrency(users: dict[str, Client], f: Findings) -> None:
    v, b, o = users["verwalter"], users["buchhaltung"], users["owner"]
    tenants = v.all("/tenants")
    tenant = tenants[0]
    # two people change different fields of the same tenant at the same moment
    # (both may edit tenants: manager and owner)
    with ThreadPoolExecutor(2) as pool:
        pool.submit(v.call, "PATCH", f"/tenants/{tenant['id']}", {"phone": "+49 30 111111"}, area="Gleichzeitig")
        pool.submit(o.call, "PATCH", f"/tenants/{tenant['id']}", {"email": "neu@stress.test"}, area="Gleichzeitig")
    after = o.ok("GET", f"/tenants/{tenant['id']}", area="Gleichzeitig") or {}
    f.check(after.get("phone") == "+49 30 111111" and after.get("email") == "neu@stress.test", "FALSCH", "Gleichzeitig",
            "Gleichzeitige Änderungen verschiedener Felder: eine Änderung ging verloren", after)
    # the same record from two forms: both opened it, the manager saves first; the owner's form
    # sends the state it was opened with (as the app's forms do) and must not overwrite silently
    v.call("PUT", f"/tenants/{tenant['id']}", {**{k: after.get(k) for k in ("full_name", "email", "phone")},
                                                "notes": "Stand A", "updated_at": after.get("updated_at")},
           area="Gleichzeitig")
    stale = dict(after, notes="Stand B, auf altem Stand bearbeitet")
    status, _ = o.call("PUT", f"/tenants/{tenant['id']}",
                       {k: stale.get(k) for k in ("full_name", "email", "phone", "notes", "updated_at")},
                       expect=(200, 409, 412), area="Gleichzeitig")
    if status == 200:
        f.add("LÜCKE", "Gleichzeitig", "Keine Konflikterkennung: wer zuletzt speichert, überschreibt die Änderung des "
                                       "anderen ohne Rückfrage")
    kept = o.ok("GET", f"/tenants/{tenant['id']}", area="Gleichzeitig") or {}
    f.check(kept.get("notes") == "Stand A", "FALSCH", "Gleichzeitig",
            "Nach abgelehnter veralteter Änderung steht nicht mehr die Änderung des ersten Benutzers", kept)
    # many payments at once for one tenant: every one credited exactly once
    contract = next(x for x in v.all("/contracts") if x["status"] == "active")
    account = v.all("/accounts")[0]["id"]
    before = {a["booking_id"] for a in b.ok("GET", "/bookings/allocations", area="Gleichzeitig") or []}

    def pay(i):
        return b.ok("POST", "/bookings", {"account_id": account, "tenant_id": contract["tenant_id"],
                                          "booking_date": "2026-06-01", "amount": 10.0 + i, "payment_text": f"Parallel {i}"},
                    area="Gleichzeitig")
    with ThreadPoolExecutor(8) as pool:
        made = [x for x in pool.map(pay, range(40)) if x]
    allocations = [a for a in (b.ok("GET", "/bookings/allocations", area="Gleichzeitig") or [])
                   if a["booking_id"] not in before and a["booking_id"] in {m["id"] for m in made}]
    per_booking = {}
    for a in allocations:
        per_booking[a["booking_id"]] = per_booking.get(a["booking_id"], 0) + a["amount"]
    wrong = [m["id"] for m in made if abs(per_booking.get(m["id"], 0) - m["amount"]) > 0.005]
    f.check(len(made) == 40 and not wrong, "FALSCH", "Gleichzeitig",
            f"Parallele Zahlungen: {len(made)}/40 angelegt, {len(wrong)} falsch zugeordnet")
    # the same rent adjustment applied twice at the same moment: one rent period only
    periods = v.ok("GET", f"/contracts/{contract['id']}/rent-periods") or [{"cold_rent": 500}]
    adj = v.ok("POST", "/rent-adjustments", {"contract_id": contract["id"], "adjustment_type": "index",
                                             "effective_date": "2028-01-01", "previous_rent": periods[-1]["cold_rent"],
                                             "new_rent": round(periods[-1]["cold_rent"] * 1.02, 2)}, area="Gleichzeitig")
    if adj:
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda _: v.call("POST", f"/rent-adjustments/{adj['id']}/apply", {}, expect=(200, 400, 409),
                                           area="Gleichzeitig"), range(4)))
        new = [p for p in v.ok("GET", f"/contracts/{contract['id']}/rent-periods") or [] if p["valid_from"][:10] == "2028-01-01"]
        f.check(len(new) == 1, "FALSCH", "Gleichzeitig", f"Mietanpassung parallel angewendet: {len(new)} Mietstände")
    # double click on "save": the same contract number twice at the same moment
    unit = next((u for u in v.all("/units") if u["status"] == "vacant"), None)
    if unit:
        body = {"contract_number": "DOPPELKLICK-1", "property_id": unit["property_id"], "unit_id": unit["id"],
                "tenant_id": tenant["id"], "start_date": f"{SPARE_YEAR + 1}-01-01", "status": "draft"}
        with ThreadPoolExecutor(3) as pool:
            list(pool.map(lambda _: v.call("POST", "/contracts", body, expect=(201, 400, 409), area="Gleichzeitig"), range(3)))
        count = sum(1 for x in v.all("/contracts") if x["contract_number"] == "DOPPELKLICK-1")
        f.check(count == 1, "FALSCH", "Gleichzeitig", f"Doppelklick auf Speichern: {count} Verträge angelegt")
    mixed_load(o.server, f, account, [t["id"] for t in tenants[:30]])


def mixed_load(server: Server, f: Findings, account: str, tenant_ids: list[str], *,
               duration: float = 30, writes_per_writer: int = 20) -> dict:
    """Ten distinct authenticated sessions: eight readers and two paced writers."""
    if duration <= 0 or writes_per_writer < 1 or not tenant_ids:
        raise ValueError("Mixed load needs a positive duration, write count and tenant IDs")
    marker = f"mixed-{uuid4().hex}"
    owner = Client(server, f, "owner")
    clients = []
    latencies, acknowledgements, errors = [], [], []
    active = {"read": 0, "write": 0, "overlap": 0}
    lock = threading.Lock()
    started = [0.0]
    barrier = threading.Barrier(10, action=lambda: started.__setitem__(0, time.perf_counter()))
    try:
        before = owner.all("/bookings", area="Last")
        for i in range(10):
            username = f"load_{marker[-8:]}_{i}"
            status, _ = owner.call("POST", "/auth/users", {
                "username": username, "email": f"{username}@stress.test", "full_name": f"Synthetic load user {i}",
                "password": PASSWORD, "role": "readonly" if i < 8 else "buchhaltung"}, expect=(201,), area="Last")
            if status != 201:
                raise RuntimeError(f"Could not create independent load user {i}")
            clients.append(Client(server, f, username))

        def request(client, method, path, body=None):
            kind, other = ("read", "write") if method == "GET" else ("write", "read")
            with lock:
                active[kind] += 1
                if active[other]:
                    active["overlap"] += 1
            t0 = time.perf_counter()
            try:
                status, content = client.call(method, path, body, area="Last", expect=(200,) if method == "GET" else (201,))
                with lock:
                    latencies.append(time.perf_counter() - t0)
                    if status != (200 if method == "GET" else 201):
                        errors.append({"method": method, "status": status})
                return status, content
            finally:
                with lock:
                    active[kind] -= 1

        def worker(i):
            client = clients[i]
            barrier.wait(timeout=30)
            if i < 8:
                n = 0
                while time.perf_counter() < started[0] + duration:
                    path = [f"/tenants/{tenant_ids[n % len(tenant_ids)]}/account", "/review", "/reports/summary",
                            "/contracts/current-rents", "/bookings?limit=200"][n % 5]
                    request(client, "GET", path)
                    n += 1
            else:
                for n in range(writes_per_writer):
                    pause = started[0] + n * duration / writes_per_writer - time.perf_counter()
                    if pause > 0:
                        time.sleep(pause)
                    payload = {"account_id": account, "booking_date": "2026-06-01", "amount": 10 + i + n,
                               "payment_text": f"{marker}-{i}-{n}"}
                    status, row = request(client, "POST", "/bookings", payload)
                    if status == 201 and isinstance(row, dict) and row.get("id"):
                        with lock:
                            acknowledgements.append((row["id"], payload))
                    elif status == 201:
                        f.add("FALSCH", "Last", "Bestätigte Buchung hat keine ID", row)

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(worker, range(10)))
        elapsed = time.perf_counter() - started[0]
        after = owner.all("/bookings", area="Last")
        stored = {row["id"]: row for row in after}
        verified = sum(all(stored.get(id_, {}).get(key) == value for key, value in payload.items())
                       for id_, payload in acknowledgements)
        expected = 2 * writes_per_writer
        unique = len({id_ for id_, _ in acknowledgements})
        f.check(len(acknowledgements) == unique == expected and verified == expected and len(after) - len(before) == expected,
                "FALSCH", "Last", f"Schreibprüfung: {len(acknowledgements)}/{expected} bestätigt, {unique} eindeutige IDs, "
                f"{verified} Inhalte korrekt, Bestandszuwachs {len(after) - len(before)}")
        f.check(not errors, "FALSCH", "Last", f"Unerwartete HTTP-Antworten im Mischbetrieb: {len(errors)}", errors[:5])
        f.check(active["overlap"] > 0, "FALSCH", "Last", "Keine gemessene Überlappung von Lese- und Schreibzugriffen")
        p95 = sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * .95))] if latencies else 0
        f.check(p95 < 2.0, "LANGSAM", "Last", f"10 parallele Benutzer: p95 {p95:.2f} s (Ziel < 2 s)")
        result = {"clients": 10, "readers": 8, "writers": 2, "duration_seconds": elapsed,
                  "requests": len(latencies), "acknowledged_writes": len(acknowledgements),
                  "verified_writes": verified, "errors": len(errors), "overlapping_requests": active["overlap"],
                  "p95_seconds": p95, "median_seconds": statistics.median(latencies) if latencies else 0}
        f.measurements["mixed_load"] = result
        f.add("HINWEIS", "Last", f"10 unabhängige Benutzer (8 Leser, 2 Schreiber): {len(latencies)} Zugriffe in {elapsed:.1f} s, "
              f"{verified}/{expected} Schreibvorgänge nachgelesen, Überlappungen {active['overlap']}, "
              f"p95 {p95:.2f} s, Fehler {len(errors)}")
        return result
    finally:
        for client in [owner, *clients]:
            client.http.close()


def run(server: Server, f: Findings) -> None:
    previous = f.phase
    f.phase = "rechte+gleichzeitig"
    server.stop()
    copy = server.clone("rechte")
    server.start()
    copy.start()
    try:
        users = setup_users(copy, f)
        concurrency(users, f)
        matrix(users, f)      # last: it locks an account on purpose
    finally:
        copy.stop()
        f.phase = previous
