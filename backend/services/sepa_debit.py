"""SEPA direct debit file for rents: the program writes the file, the bank collects.

For one bank account (the creditor account) and one month, the preview lists every
contract of that account's portfolio whose tenant pays by direct debit, with what is
still open of the receivables due in that month and what keeps it out of the file
(no valid IBAN, no mandate reference or date, nothing open, already in a file). The
file is a pain.008.001.08 message (sepa_rules) that the user uploads to online
banking; nothing is sent from here.

The creditor identifier and name are remembered per account as an installation-wide
rule (`sepa_creditor:<account id>`, scope "global") with revision and audit journal.
Every file is recorded in the audit journal (action REGISTER) with its receivables,
so a second file for the same receivables is refused unless the user confirms it. A
repeated request with the same idempotency key returns the same file (same message
id) instead of a new one.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from ..db.daily_models import SettingRuleORM
from ..domain.clock import local_today
from ..domain.money import ZERO, money
from ..domain.receivables import UNPAID_RECEIVABLE_STATUSES
from ..store_errors import NotFoundError
from . import daily_state as state
from . import document_versions as archive
from . import sepa_rules as rules
from .portfolio_scope import scope_context, scope_from_user
from .settings_catalogue import record_audit, rule

REGISTER = "sepa_debit_file"
WRITE_AREA = "/receivables"
SCOPE = "global"
MONTH = re.compile(r"^(20\d\d)-(0[1-9]|1[0-2])$")
MAX_TRANSACTIONS = 2000


def creditor_key(account_id: str) -> str:
    return f"sepa_creditor:{account_id}"


def _today() -> date:
    return local_today()


def _month(value: Any) -> tuple[date, date]:
    match = MONTH.match(value) if isinstance(value, str) else None
    if not match:
        raise HTTPException(422, "Monat im Format JJJJ-MM angeben.")
    year, month = int(match.group(1)), int(match.group(2))
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return date(year, month, 1), end


def _day(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else value if isinstance(value, date) else None  # type: ignore[return-value]
    except ValueError:
        pass
    raise HTTPException(422, f"{label}: Datum im Format JJJJ-MM-TT angeben.")


def _account(store, account_id: Any):
    if not isinstance(account_id, str) or not account_id:
        raise HTTPException(422, "Bitte das Konto wählen, auf das eingezogen wird.")
    try:
        account = store.get_account(account_id)
    except NotFoundError:
        raise HTTPException(404, "Das Konto wurde nicht gefunden.") from None
    problem = rules.iban_problem(account.iban)
    if problem:
        raise HTTPException(422, f"Das Konto „{account.name}“ hat keine gültige IBAN: {problem} "
                                 "Bitte unter Konten nachtragen.")
    if rules.bic_problem(account.bic):
        raise HTTPException(422, f"Das Konto „{account.name}“ hat keinen gültigen BIC.")
    return account


def _creditor(unit, account) -> dict:
    saved = rule(unit, SCOPE, creditor_key(account.id))
    value = saved.get("payload", {}).get("value") or {}
    return {"revision": saved["revision"], "creditor_id": value.get("creditor_id") or "",
            "creditor_name": value.get("creditor_name") or ""}


def _suggested_name(unit, account) -> str:
    """A first suggestion for the creditor name: the letterhead's sender, else the portfolio's owner."""
    try:
        from .letterhead import source
        sender = source(unit, None)["sender_name"]
    except Exception:              # a damaged letterhead must not block the direct debit
        sender = ""
    if sender:
        return sender
    portfolio = unit.store.get_portfolio(account.portfolio_id)
    return (portfolio.owner_name or portfolio.name or "").strip()


def _files(unit) -> list[dict]:
    """Files written so far (newest first), from the audit journal."""
    if unit.db is not None:
        from ..db.orm_models import AuditLogORM
        rows = [(row.timestamp, row.changes) for row in unit.db.scalars(
            select(AuditLogORM).where(AuditLogORM.action == REGISTER))]
    else:
        from .. import audit as audit_service
        rows = [(entry.timestamp, entry.changes) for entry in audit_service._audit_store.list_all(action=REGISTER)]
    files = []
    for timestamp, changes in rows:
        try:
            data = json.loads(changes or "{}")
        except ValueError:
            continue
        files.append({**data, "created_at": timestamp.isoformat() if timestamp else None})
    return sorted(files, key=lambda item: item.get("created_at") or "", reverse=True)


def _earlier(files: list[dict]) -> dict[str, list[dict]]:
    """receivable id → the files that already contained it."""
    found: dict[str, list[dict]] = {}
    for item in files:
        for line in item.get("items") or []:
            for receivable_id in line.get("receivable_ids") or []:
                found.setdefault(receivable_id, []).append(
                    {"message_id": item.get("message_id"), "created_at": item.get("created_at"),
                     "collection_date": item.get("collection_date")})
    return found


def _rent_due(store, contracts: list, start: date, end: date, today: date) -> dict[str, list[dict]]:
    """Per contract the monthly rent falling due in the month, as far as payments booked up to today
    have not paid it (the tenant account's FIFO, as in the rent overview and the liquidity plan)."""
    from ..domain.lease_engine import LeaseEngine
    from .payment_allocations import contract_ledger, credited_by_tenant
    from .read_cache import CachedReads
    credited = credited_by_tenant(store, {contract.tenant_id for contract in contracts if contract.tenant_id})
    reads = CachedReads(store)
    found: dict[str, list[dict]] = {}
    last = end - timedelta(days=1)
    for contract in contracts:
        claims, payments = contract_ledger(reads, contract, last, credited.get(contract.tenant_id, []), payments_until=today)
        for line in LeaseEngine.build_settlement_report(claims, payments, today=today):
            # monthly rent only: arrears carried over and returned payments are a matter for dunning
            if line.label is None and start <= line.due_date < end and line.outstanding_amount > ZERO:
                found.setdefault(contract.id, []).append({
                    "id": f"rent:{contract.id}:{line.period_start.isoformat()}", "due_date": line.due_date.isoformat(),
                    "description": "Miete", "open": str(money(line.outstanding_amount))})
    return found


def _lines(unit, account, start: date, end: date, today: date) -> list[dict]:
    """Every contract of the account's portfolio whose tenant pays by direct debit, with the rent and
    the stored receivables (e.g. a utility statement's back payment) still open in the month."""
    store = unit.store
    from ..domain.occupancy import NON_BILLABLE_STATUSES
    from .receivable_residuals import ResidualReader
    properties = {item.id: item for item in store.list_properties() if item.portfolio_id == account.portfolio_id}
    contracts = [item for item in store.list_contracts()
                 if item.property_id in properties and item.status not in NON_BILLABLE_STATUSES]
    tenants = {item.id: item for item in store.list_tenants()}
    units = {item.id: item for item in store.list_units()}
    portfolio = store.get_portfolio(account.portfolio_id)
    payers = [contract for contract in contracts
              if contract.tenant_id in tenants and tenants[contract.tenant_id].payment_method == "sepa_direct_debit"]
    wanted = {contract.id for contract in payers}
    rent = _rent_due(store, payers, start, end, today)
    due = [item for item in store.list_receivables() if item.contract_id in wanted and start <= item.due_date < end
           and item.status in UNPAID_RECEIVABLE_STATUSES]
    reader = ResidualReader(store) if due else None
    earlier = _earlier(_files(unit))
    lines = []
    for contract in sorted(payers, key=lambda item: item.contract_number or ""):
        tenant = tenants[contract.tenant_id]
        open_items = list(rent.get(contract.id, []))
        for receivable in sorted((item for item in due if item.contract_id == contract.id), key=lambda item: item.due_date):
            assert reader is not None
            balance = money(reader.balance(receivable, today))
            if balance > ZERO:
                open_items.append({"id": receivable.id, "due_date": receivable.due_date.isoformat(),
                                   "description": receivable.description or "Forderung", "open": str(balance)})
        for item in open_items:
            item["earlier"] = earlier.get(item["id"], [])
        total = sum((Decimal(item["open"]) for item in open_items), ZERO)
        problems = [problem for problem in (
            rules.iban_problem(tenant.sepa_iban), rules.bic_problem(tenant.sepa_bic),
            rules.mandate_problem(tenant.sepa_mandate),
            None if tenant.sepa_mandate_date else "Datum der Mandatsunterschrift fehlt.",
            None if (portfolio.currency or "EUR") == "EUR" else "SEPA-Lastschriften gibt es nur in Euro.") if problem]
        if tenant.sepa_mandate_date and tenant.sepa_mandate_date > today:
            problems.append("Das Mandat ist auf einen Tag in der Zukunft datiert.")
        holder = (tenant.sepa_account_holder or tenant.full_name or "").strip()
        if not rules.text(holder, 70):
            problems.append("Kontoinhaber fehlt.")
        place = units.get(contract.unit_id)
        lines.append({
            "contract_id": contract.id, "contract_number": contract.contract_number, "tenant_id": tenant.id,
            "tenant_name": tenant.full_name, "account_holder": holder, "property_name": properties[contract.property_id].name,
            "unit_label": place.label if place else None, "iban": rules.mask_iban(tenant.sepa_iban),
            "mandate_reference": tenant.sepa_mandate, "mandate_date": tenant.sepa_mandate_date.isoformat() if tenant.sepa_mandate_date else None,
            "receivables": open_items, "amount": str(total), "problems": problems,
            "repeated": any(item["earlier"] for item in open_items),
            "ready": not problems and total > ZERO})
    return lines


def preview(store, actor_id: str, account_id: str, month: str, collection_date: str | None = None) -> dict:
    start, end = _month(month)
    today = _today()
    with archive.work(store, actor_id) as unit, scope_context(scope_from_user(unit.user)):
        account = _account(unit.store, account_id)
        lines = _lines(unit, account, start, end, today)
        earliest = rules.next_business_day(today + timedelta(days=1))
        day = _day(collection_date, "Fälligkeit") if collection_date else rules.next_business_day(max(start, earliest))
        ready = [line for line in lines if line["ready"]]
        return {"account": {"id": account.id, "name": account.name, "iban": rules.mask_iban(account.iban),
                            "bic": account.bic, "portfolio_id": account.portfolio_id},
                "creditor": {**_creditor(unit, account), "suggested_name": _suggested_name(unit, account)}, "month": month, "collection_date": day.isoformat(),
                "collection_date_problem": rules.collection_date_problem(day, today),
                "lines": lines, "ready_count": len(ready),
                "ready_total": str(sum((Decimal(line["amount"]) for line in ready), ZERO)),
                "files": [{key: item.get(key) for key in ("message_id", "created_at", "collection_date", "month", "count", "total",
                                                          "account_id")}
                          for item in _files(unit) if item.get("account_id") == account.id][:10]}


def _remember_creditor(unit, account, key: str, creditor_id: str, creditor_name: str) -> None:
    before = _creditor(unit, account)
    value = {"creditor_id": creditor_id, "creditor_name": creditor_name}
    if (before["creditor_id"], before["creditor_name"]) == (creditor_id, creditor_name):
        return
    stored = {"value": value}
    rule_key = creditor_key(account.id)
    if unit.db is None:
        unit.insert(state.memory(unit, "rules"), (SCOPE, rule_key), {"revision": before["revision"] + 1, "payload": stored})
    else:
        row = unit.db.scalar(select(SettingRuleORM).where(SettingRuleORM.scope == SCOPE,
                                                          SettingRuleORM.key == rule_key).with_for_update())
        if row is None:
            row = SettingRuleORM(scope=SCOPE, key=rule_key)
            unit.db.add(row)
        row.revision, row.payload, row.updated_at = before["revision"] + 1, stored, state.now()
        unit.db.flush()
    record_audit(unit, key, "settings_change", SCOPE, {rule_key: {k: before[k] for k in ("creditor_id", "creditor_name")}},
                 {rule_key: value})


def _register(unit, actor: dict, record: dict) -> None:
    from ..models import AuditLogEntry
    entry = AuditLogEntry(id=f"sepa:{record['message_id']}", user_id=str(actor.get("id")), username=actor.get("username"),
                          action=REGISTER, entity_type="sepa_debit_file", entity_id=record["message_id"],
                          changes=json.dumps(record, ensure_ascii=False), timestamp=datetime.now(timezone.utc))
    if unit.db is not None:
        from ..db.orm_models import AuditLogORM
        unit.db.add(AuditLogORM(**entry.model_dump()))
        unit.db.flush()
    else:
        from .. import audit as audit_service
        audit_service._audit_store.add(entry)


def create(store, actor_id: str, payload: dict) -> dict:
    """Write the file for the chosen contracts; returns the XML with a summary."""
    start, end = _month(payload.get("month"))
    day = _day(payload.get("collection_date"), "Fälligkeit")
    key = payload.get("idempotency_key")
    if not isinstance(key, str) or not 8 <= len(key) <= 120:
        raise HTTPException(422, "Ungültige Vorgangskennung.")
    creditor_id = rules.compact(payload.get("creditor_id"))
    creditor_name = " ".join(str(payload.get("creditor_name") or "").split())
    problem = rules.creditor_id_problem(creditor_id)
    if problem:
        raise HTTPException(422, problem)
    if not rules.text(creditor_name, 70):
        raise HTTPException(422, "Bitte den Namen des Zahlungsempfängers angeben (wie beim Gläubiger-ID-Antrag).")
    chosen = payload.get("contract_ids")
    if not isinstance(chosen, list) or not chosen or not all(isinstance(item, str) for item in chosen):
        raise HTTPException(422, "Bitte mindestens einen Vertrag auswählen.")
    if len(set(chosen)) > MAX_TRANSACTIONS:
        raise HTTPException(422, f"Höchstens {MAX_TRANSACTIONS} Lastschriften je Datei.")
    allow_repeat = payload.get("allow_repeat") is True
    request = {"account_id": payload.get("account_id"), "month": payload.get("month"), "collection_date": day.isoformat(),
               "creditor_id": creditor_id, "creditor_name": creditor_name, "contract_ids": sorted(set(chosen)),
               "allow_repeat": allow_repeat}
    fingerprint = state.digest("sepa_debit_file", request)
    today = _today()
    with archive.work(store, actor_id, write_areas=(WRITE_AREA,)) as unit, scope_context(scope_from_user(unit.user)):
        saved = state.replay(unit, key, fingerprint)
        if saved is not None:
            return saved
        problem = rules.collection_date_problem(day, today)
        if problem:
            raise HTTPException(422, problem)
        account = _account(unit.store, payload.get("account_id"))
        lines = {line["contract_id"]: line for line in _lines(unit, account, start, end, today)}
        missing = [item for item in chosen if item not in lines]
        if missing:
            raise HTTPException(409, "Ein gewählter Vertrag gehört nicht zu diesem Konto oder zahlt nicht per Lastschrift. "
                                     "Bitte die Vorschau neu laden.")
        picked = [lines[item] for item in dict.fromkeys(chosen)]
        blocked = [line for line in picked if not line["ready"]]
        if blocked:
            first = blocked[0]
            reason = "; ".join(first["problems"]) or "nichts offen"
            raise HTTPException(409, f"{first['contract_number']} ({first['tenant_name']}): {reason} Bitte die Vorschau neu laden.")
        repeated = [line for line in picked if line["repeated"]]
        if repeated and not allow_repeat:
            names = ", ".join(line["contract_number"] for line in repeated[:5])
            raise HTTPException(409, f"Für {names} wurden diese Sollstellungen schon in eine Lastschriftdatei geschrieben. "
                                     "Nur wenn die Bank sie nicht eingezogen hat, bestätigen Sie die erneute Aufnahme.")
        tenants = {item.id: item for item in unit.store.list_tenants()}
        created = datetime.now(timezone.utc)
        message_id = rules.identifier(f"IMMO-{created:%Y%m%d%H%M%S}-{state.digest('id', key)[:8]}")
        transactions = []
        label = f"{start:%m/%Y}"
        for line in picked:
            tenant = tenants[line["tenant_id"]]
            descriptions = ", ".join(dict.fromkeys(item["description"] for item in line["receivables"]))
            transactions.append({
                "end_to_end_id": rules.identifier(f"{start:%Y%m}-{line['contract_number'] or line['contract_id']}"),
                "amount": Decimal(line["amount"]), "mandate_id": tenant.sepa_mandate.strip(),
                "mandate_date": tenant.sepa_mandate_date, "debtor_name": line["account_holder"],
                "debtor_iban": tenant.sepa_iban, "debtor_bic": tenant.sepa_bic,
                "remittance": f"{descriptions} {label} Vertrag {line['contract_number'] or ''}".strip()})
        ends = [item["end_to_end_id"] for item in transactions]
        for index, value in enumerate(ends):          # unique within the file
            if ends.count(value) > 1:
                transactions[index]["end_to_end_id"] = rules.identifier(f"{value[:30]}-{index + 1}")
        xml = rules.pain008(message_id=message_id, created=created.replace(tzinfo=None), creditor_name=creditor_name,
                            creditor_iban=account.iban, creditor_bic=account.bic, creditor_id=creditor_id,
                            collection_date=day, transactions=transactions)
        total = sum((item["amount"] for item in transactions), ZERO)
        record = {"message_id": message_id, "account_id": account.id, "month": payload.get("month"),
                  "collection_date": day.isoformat(), "count": len(transactions), "total": str(total),
                  "creditor_id": creditor_id,
                  "items": [{"contract_id": line["contract_id"], "receivable_ids": [item["id"] for item in line["receivables"]],
                             "amount": line["amount"], "end_to_end_id": transaction["end_to_end_id"]}
                            for line, transaction in zip(picked, transactions)]}
        _remember_creditor(unit, account, key, creditor_id, creditor_name)
        _register(unit, unit.user, record)
        result = {**record, "filename": f"SEPA-Lastschriften_{start:%Y-%m}_{day.isoformat()}.xml",
                  "xml": xml.decode("utf-8"),
                  "lines": [{"contract_number": line["contract_number"], "tenant_name": line["tenant_name"],
                             "amount": line["amount"]} for line in picked]}
        state.remember(unit, key, fingerprint, result)
        return result
