"""Checks against the independent ledger, and a fingerprint of the data for save/load comparisons."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from .core import Client, Findings
from .ledger import due_until, money, step_on
from .timeline import Simulation

TOLERANCE = Decimal("0.02")


def check_accounts(sim: Simulation, client: Client, as_of: date) -> None:
    """Per tenant: rent due, payments and their split against the ledger."""
    f = sim.f
    by_tenant = defaultdict(list)
    for t in sim.w.tenancies:
        if id(t) in sim.created and t.tenant.id:
            by_tenant[t.tenant.id].append(t)
    for tenant_id, tenancies in by_tenant.items():
        account = client.ok("GET", f"/tenants/{tenant_id}/account", params={"as_of": as_of.isoformat()}, area="Mieterkonto")
        if not account:
            continue
        name = tenancies[0].tenant.name
        rows = {r["contract_id"]: r for r in account["contracts"]}
        for t in tenancies:
            row = rows.get(t.id)
            if not f.check(row is not None, "FALSCH", "Mieterkonto", f"{name}: Vertrag {t.number} fehlt im Konto"):
                continue
            expected = due_until(t, as_of) if t.start <= as_of else Decimal("0")
            f.check(abs(money(row["expected"]) - expected) <= TOLERANCE, "FALSCH", "Mieterkonto",
                    f"{name} {t.number}: Soll {row['expected']} statt {expected} (Stichtag {as_of})",
                    {"steps": [(str(s[0]), s[1], s[2], s[3]) for s in t.steps]})
        paid = sim.ledger.payments.get(tenant_id, Decimal("0"))
        f.check(abs(money(account["paid_total"]) - paid) <= TOLERANCE, "FALSCH", "Mieterkonto",
                f"{name}: gezahlt gesamt {account['paid_total']} statt {paid}")
        credited = sum(money(r["paid"]) for r in account["contracts"])
        open_rest = sum(money(u["unassigned"]) for u in account["unassigned"])
        f.check(abs(credited + open_rest - money(account["paid_total"])) <= TOLERANCE * len(account["contracts"] or [1]),
                "FALSCH", "Mieterkonto", f"{name}: Verträgen zugeordnet {credited} + offen {open_rest} "
                                         f"≠ gezahlt {account['paid_total']}")
        for row in account["contracts"]:
            f.check(row["outstanding"] >= 0 and row["overpaid"] >= 0 and not (row["outstanding"] and row["overpaid"]),
                    "FALSCH", "Mieterkonto", f"{name} {row['contract_number']}: offen und überzahlt zugleich", row)


def check_rents(sim: Simulation, client: Client, as_of: date) -> None:
    f = sim.f
    current = client.ok("GET", "/contracts/current-rents", params={"as_of": as_of.isoformat()}, area="Mieten") or {}
    for t in sim.w.tenancies:
        if id(t) not in sim.created or t.start > as_of or (t.end and t.end < as_of):
            continue
        expected = step_on(t, as_of)
        got = current.get(t.id)
        if expected and f.check(got is not None, "FALSCH", "Mieten", f"{t.number}: keine aktuelle Miete"):
            f.check(abs(got["cold_rent"] - expected[0]) < 0.005, "FALSCH", "Mieten",
                    f"{t.number}: aktuelle Kaltmiete {got['cold_rent']} statt {expected[0]}")
    sample = [t for t in sim.w.tenancies if id(t) in sim.created][:: max(1, len(sim.created) // 40)]
    for t in sample:
        periods = client.ok("GET", f"/contracts/{t.id}/rent-periods", area="Mietverlauf") or []
        got = [(p["valid_from"][:10], round(p["cold_rent"], 2), round(p["service_charge_advance"], 2)) for p in periods]
        want = [(s[0].isoformat(), round(s[1], 2), round(s[2], 2)) for s in sorted(t.steps, key=lambda s: s[0])]
        f.check(got == want, "FALSCH", "Mietverlauf", f"{t.number}: Mietverlauf weicht ab", {"app": got, "soll": want})


def check_overview(sim: Simulation, client: Client, as_of: date) -> None:
    """Dashboard, lists and reports must agree with each other and with the world."""
    f = sim.f
    units = client.all("/units", area="Übersicht")
    contracts = client.all("/contracts", area="Übersicht")
    f.check(len(units) == len(sim.w.units), "FALSCH", "Übersicht", f"{len(units)} Einheiten statt {len(sim.w.units)}")
    f.check(len(contracts) == len(sim.created), "FALSCH", "Übersicht", f"{len(contracts)} Verträge statt {len(sim.created)}")
    running = sum(1 for t in sim.w.tenancies if id(t) in sim.created and t.start <= as_of and (not t.end or t.end >= as_of))
    occupied = len({t.unit.id for t in sim.w.tenancies if id(t) in sim.created and t.start <= as_of
                    and (not t.end or t.end >= as_of)})
    dashboard = client.ok("GET", "/dashboard/stats", area="Übersicht") or {}
    if as_of >= sim.w.end:        # the dashboard counts for today
        f.check(dashboard.get("active_contracts") == running, "FALSCH", "Dashboard",
                f"{dashboard.get('active_contracts')} aktive Verträge statt {running}")
        f.check(dashboard.get("occupied_units") == occupied, "FALSCH", "Dashboard",
                f"{dashboard.get('occupied_units')} vermietete Einheiten statt {occupied}")
        occupancy = client.ok("GET", "/reports/occupancy", area="Berichte") or {}
        f.check(occupancy.get("rentedUnits") == occupied, "FALSCH", "Berichte",
                f"Belegungsbericht: {occupancy.get('rentedUnits')} vermietet statt {occupied}")
    bookings = client.all("/bookings", area="Übersicht")
    total = sum(money(b["amount"]) for b in bookings)
    f.check(abs(total - sim.ledger.booked_total) <= Decimal("0.05") * max(1, len(bookings) // 1000), "FALSCH", "Buchungen",
            f"Summe aller Buchungen {total} statt {sim.ledger.booked_total}")
    review = client.ok("GET", "/review", area="Prüfliste") or {}
    sim.f.add("HINWEIS", "Prüfliste", f"Stand {as_of}: {review.get('count', '?')} Einträge",
              {k: sum(1 for i in review.get("items", []) if i["kind"] == k)
               for k in {i["kind"] for i in review.get("items", [])}})
    for path in ["/reports/summary", "/reports/finance", "/reports/receivables-aging", "/reports/cashflow",
                 "/reports/liquidity-forecast", "/reports/contracts-expiring", "/reports/maintenance-costs",
                 "/admin/integrity-check"]:
        client.call("GET", path, area="Berichte")


def run_checks(sim: Simulation, as_of: date) -> None:
    previous = sim.f.phase
    sim.f.phase = f"prüfung {as_of}"
    client = sim.u["owner"]
    check_accounts(sim, client, as_of)
    check_rents(sim, client, as_of)
    check_overview(sim, client, as_of)
    sim.f.phase = previous


def fingerprint(client: Client) -> dict:
    """Everything that must survive a restart, an export/import or a backup/restore."""
    entities = client.ok("GET", "/data/export", area="Speichern") or {}
    counts = {k: len(v) for k, v in entities.items() if isinstance(v, list)}
    digest = {}
    for name, rows in entities.items():
        if not isinstance(rows, list):
            continue
        canon = sorted(json.dumps({k: v for k, v in r.items() if k not in ("updated_at",)}, sort_keys=True, default=str)
                       for r in rows if isinstance(r, dict))
        digest[name] = hashlib.sha256("\n".join(canon).encode()).hexdigest()[:16]
    accounts = {}
    for tenant in client.all("/tenants", area="Speichern")[:60]:
        acc = client.ok("GET", f"/tenants/{tenant['id']}/account", area="Speichern") or {}
        accounts[tenant["id"]] = (acc.get("paid_total"), [(r["contract_number"], r["expected"], r["paid"])
                                                          for r in acc.get("contracts", [])])
    rents = client.ok("GET", "/contracts/current-rents", area="Speichern") or {}
    return {"counts": counts, "digest": digest, "accounts": accounts, "rents": rents,
            "review": (client.ok("GET", "/review", area="Speichern") or {}).get("count")}


def compare(f: Findings, before: dict, after: dict, what: str) -> None:
    for name, count in before["counts"].items():
        f.check(after["counts"].get(name) == count, "KRITISCH", "Speichern/Laden",
                f"{what}: {name} {count} → {after['counts'].get(name)}")
    changed = [n for n, d in before["digest"].items() if after["digest"].get(n) != d and n not in ("change_history",)]
    f.check(not changed, "KRITISCH", "Speichern/Laden", f"{what}: Inhalte verändert in {', '.join(changed)}")
    diff_accounts = [k for k, v in before["accounts"].items() if after["accounts"].get(k) != v]
    f.check(not diff_accounts, "KRITISCH", "Speichern/Laden", f"{what}: {len(diff_accounts)} Mieterkonten verändert",
            diff_accounts[:3])
    f.check(before["rents"] == after["rents"], "KRITISCH", "Speichern/Laden", f"{what}: aktuelle Mieten verändert")
    f.check(before["review"] == after["review"], "FALSCH", "Speichern/Laden",
            f"{what}: Prüfliste {before['review']} → {after['review']} Einträge")
