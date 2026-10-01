"""Read-only tenant metadata graph for 111ea636; not a complete legal export.
Caller supplies authorization and a coherent snapshot. No writes/file access.
"""
import json
from contextlib import nullcontext
from typing import Any, NoReturn, cast

from pydantic import BaseModel

from .. import models as m
from ..storage import NotFoundError
from .billing_settlement import settlements as _all_settlements
from .payments import Payment


class TenantExportError(RuntimeError):
    """Failed read or invalid graph; never publish partial output."""


class TenantNotFoundError(LookupError):
    """Only the initial tenant lookup may raise this."""


# Collection, declared model, nullable contract_id.
_CONTRACT_COLLECTIONS = (
    ("documents", m.Document, True),
    ("deposits", m.Deposit, False),
    ("receivables", m.Receivable, False),
    ("rent_charges", m.RentCharge, False),
    ("rent_adjustments", m.RentAdjustment, False),
    ("handover_protocols", m.HandoverProtocol, False),
    ("utility_statements", m.UtilityStatement, False),
    ("message_threads", m.MessageThread, True),
)


def _settlements(store):
    filtered = getattr(store, "list_tenant_billing_settlements", None)
    return filtered() if filtered else _all_settlements(store)


def _fail(reason: str) -> NoReturn:
    raise TenantExportError(reason)


def _id(value: Any, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if (not isinstance(value, str) or not value or value.strip() != value
            or any(ord(char) < 32 for char in value)):
        _fail("Invalid relationship identifier")
    return value


def _dump(record: Any, expected: type[BaseModel]) -> dict:
    if not isinstance(record, expected):
        _fail("Unexpected record type")
    # The compatibility layer adds genuine declared fields to typed subclasses.
    # Include that record's declared fields; arbitrary extras/computed values
    # still cannot enter the export and financial descriptions are preserved.
    value = record.model_dump(mode="json", include=set(type(record).model_fields), warnings="error")
    value = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    _id(value["id"])
    return value


def _rows(records: Any, expected: type[BaseModel]) -> list[dict]:
    # Reject paginated envelopes/None: store lists must be complete.
    if not isinstance(records, (list, tuple)):
        _fail("Incomplete store list")
    result = [_dump(record, expected) for record in records]
    if len({row["id"] for row in result}) != len(result):
        _fail("Duplicate record identifiers")
    return sorted(result, key=lambda row: row["id"])


def _read(store: Any, method: str, expected: type[BaseModel]) -> list[dict]:
    try:
        return _rows(getattr(store, method)(), expected)
    except Exception as exc:
        raise TenantExportError(f"Unable to read {method}; no partial export") from exc


def _select(rows: list[dict], field: str, allowed: set, optional: bool = False) -> list[dict]:
    return [row for row in rows if _id(row[field], optional=optional) in allowed]


def _index(rows: list[dict]) -> dict[str, dict]:
    return {row["id"]: row for row in rows}


def _related(index: dict, key: Any, field: str, expected: str) -> dict:
    row = index.get(_id(key))
    if row is None or row[field] != expected:
        _fail("Missing or conflicting relation")
    return row


def _csv_ids(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if not isinstance(value, str):
        _fail("Invalid attachment identifier list")
    return list(dict.fromkeys(cast(str, _id(part.strip())) for part in value.split(",")))


def _verify_evidence(statement: dict, charges: dict, payments: dict) -> None:
    details = statement["advance_details"]
    if details is None:  # Older snapshots legitimately have no evidence array.
        return
    for detail in details:
        if not isinstance(detail, dict):
            _fail("Invalid advance evidence")
        charge = _related(charges, detail["rent_charge_id"], "contract_id", statement["contract_id"])

        def receipt(key: Any) -> dict:
            row = _related(payments, key, "entity_type", "rent_charge")
            if row["entity_id"] != charge["id"]:
                _fail("Evidence references a different charge")
            return row

        ids = detail.get("receipt_ids", [])
        if not isinstance(ids, list):
            _fail("Invalid receipt evidence list")
        for key in ids:
            receipt(key)
        for name in ("excluded_receipts", "reversals_after_cutoff"):
            entries = detail.get(name, [])
            if not isinstance(entries, list):
                _fail("Invalid receipt evidence")
            for entry in entries:
                if not isinstance(entry, dict):
                    _fail("Invalid receipt evidence entry")
                row = receipt(entry["receipt_id"])
                if "reversal_id" in entry:
                    if (row["reversal"] is None
                            or _id(entry["reversal_id"]) != row["reversal"]["id"]):
                        _fail("Conflicting evidence reversal")


def _graph(store: Any, tenant_id: str) -> dict:
    try:
        tenant = store.get_tenant(tenant_id)
    except NotFoundError as exc:
        raise TenantNotFoundError("Tenant not found") from exc
    tenant = _dump(tenant, m.Tenant)
    if tenant["id"] != tenant_id:
        _fail("Conflicting tenant lookup")

    contracts = _select(_read(store, "list_contracts", m.Contract), "tenant_id", {tenant_id})
    contract_map = _index(contracts)
    ids = set(contract_map)
    data: dict[str, Any] = {"tenant": tenant, "contracts": contracts}
    for name, model, optional in _CONTRACT_COLLECTIONS:
        data[name] = _select(_read(store, f"list_{name}", model), "contract_id", ids, optional)

    data["billing_settlements"] = _select(
        _rows(_settlements(store), m.BillingSettlement), "contract_id", ids,
    )
    all_bookings = _read(store, "list_bookings", m.Booking)
    data["bookings"] = _select(all_bookings, "tenant_id", {tenant_id}, True)
    booking_map = _index(all_bookings)
    own_bookings = _index(data["bookings"])
    threads = _index(data["message_threads"])
    handovers = _index(data["handover_protocols"])
    data["messages"] = _select(_read(store, "list_messages", m.Message), "thread_id", set(threads))
    data["meter_readings"] = _select(
        _read(store, "list_meter_readings", m.MeterReading), "handover_id", set(handovers),
    )

    for name in ("documents", "message_threads", "handover_protocols", "utility_statements"):
        for row in data[name]:
            contract = contract_map[row["contract_id"]]
            for field in ("property_id", "unit_id"):
                if field in row and row[field] is not None and row[field] != contract[field]:
                    _fail("Conflicting contract location")

    claims = _index(data["receivables"])
    charges = _index(data["rent_charges"])
    targets = {("receivable", key): row for key, row in claims.items()}
    targets.update({("rent_charge", key): row for key, row in charges.items()})
    data["payments"] = []
    reversal_ids = set()
    for payment in _read(store, "list_payments", Payment):
        kind, key = payment["entity_type"], _id(payment["entity_id"])
        if kind not in {"receivable", "rent_charge"}:
            _fail("Unknown payment target type")
        bank_id = _id(payment["booking_id"], optional=True)
        if (kind, key) not in targets:
            if bank_id in own_bookings:
                _fail("Tenant booking has a foreign obligation")
            continue
        if bank_id is not None:
            bank = booking_map.get(bank_id)
            if bank is None or bank["tenant_id"] not in {None, tenant_id}:
                _fail("Invalid payment booking reference")
        reversal = payment["reversal"]
        if reversal is not None:
            rid = _id(reversal["id"])
            if reversal["payment_id"] != payment["id"] or rid in reversal_ids:
                _fail("Invalid payment reversal reference")
            reversal_ids.add(rid)
        data["payments"].append(payment)
    payments = _index(data["payments"])

    statements = _index(data["utility_statements"])
    roots = {}
    for statement in data["utility_statements"]:
        row, visited = statement, set()
        while True:
            if row["id"] in visited:
                _fail("Cyclic statement revision chain")
            visited.add(row["id"])
            source = _id(row["source_statement_id"], optional=True)
            if source is None:
                roots[statement["id"]] = row["id"]
                break
            row = _related(statements, source, "contract_id", statement["contract_id"])
        _verify_evidence(statement, charges, payments)
    for claim in data["receivables"]:
        source = _id(claim["statement_id"], optional=True)
        if source is not None:
            _related(statements, source, "contract_id", claim["contract_id"])
    for settlement in data["billing_settlements"]:
        statement = _related(statements, settlement["statement_id"], "contract_id", settlement["contract_id"])
        if (settlement["billing_period_id"] != statement["billing_period_id"]
                or settlement["source_statement_id"] != statement["source_statement_id"]
                or settlement["root_statement_id"] != roots[statement["id"]]):
            _fail("Conflicting settlement source chain")
        claim_id = _id(settlement["receivable_id"], optional=True)
        if claim_id is not None:  # Includes the legitimate legacy credit reference.
            claim = _related(claims, claim_id, "contract_id", settlement["contract_id"])
            if claim["statement_id"] != statement["id"]:
                _fail("Conflicting settlement receivable")

    documents = _index(data["documents"])
    redactions = []
    for message in data["messages"]:
        original = _csv_ids(message["attachment_ids"])
        allowed = [key for key in original if key in documents]
        if len(allowed) != len(original):
            redactions.append({"collection": "messages", "id": message["id"],
                               "field": "attachment_ids", "omitted_count": len(original) - len(allowed)})
        message["attachment_ids"] = (",".join(allowed) or None) if original else message["attachment_ids"]

    for name, fields in (
        ("documents", ("file_url",)),
        ("bookings", ("receipt_url",)),
        ("meter_readings", ("photo_url",)),
        ("handover_protocols", ("photos", "tenant_signature", "landlord_signature")),
        ("message_threads", ("participant_ids",)),
    ):
        for row in data[name]:
            for field in fields:
                if row[field] is not None:
                    redactions.append({"collection": name, "id": row["id"], "field": field})
                row.pop(field)

    return {
        "schema_version": "tenant-data-graph/1",
        "scope": {
            "selection": "explicit_tenant_contract_relationships",
            "file_content": "excluded; metadata only",
            "unassigned_bookings": "payment.booking_id only; no expansion",
            "unlinked_records": "not searched by name, email, property or unit",
            "not_covered": ["contacts", "maintenance_cases", "tasks", "calendar_events",
                            "standalone_meter_readings", "shared_billing_periods",
                            "property_cost_documents", "notifications", "audit_history"],
            "redactions": redactions,
        },
        **data,
    }


def tenant_data_graph(store: Any, tenant_id: str) -> dict:
    """Detached JSON; requires a clean, consistent SQL or memory snapshot."""
    _id(tenant_id)
    try:
        db = getattr(store, "db", None)
        if db is not None and (db.new or db.dirty or db.deleted):
            _fail("Export requires a clean read session")
        with db.no_autoflush if db is not None else nullcontext():
            return _graph(store, tenant_id)
    except (TenantExportError, TenantNotFoundError):
        raise
    except Exception as exc:
        raise TenantExportError("Tenant graph export failed; no partial export") from exc
