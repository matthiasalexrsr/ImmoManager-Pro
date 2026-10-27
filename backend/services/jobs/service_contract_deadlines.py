"""Daily reminders of service contract deadlines as a durable installation job.

For every contract the job looks at the notice deadline, price guarantee ends and the
contract end whose reminder window (the contract's reminder_days) has begun. Each
deadline becomes one task (due on the deadline, at the first location's property) and
one notification, exactly once: the occurrence ledger keys it by contract, kind and
deadline date (rule version v1). A changed term gives a new date and a new reminder;
the same deadline is never reminded twice, by any worker. Chunks of CHUNK contracts
commit with their ledger rows and checkpoint.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from ...models import NotificationCreate, TaskCreate
from ...store_errors import NotFoundError
from ..service_contracts import Deadline, due_reminders, provider_name
from .core import JobContext

KIND = "service_contracts.deadlines"
CHUNK = 200
RULE_VERSION = "v1"


def rule_key(contract_id: str, kind: str) -> str:
    return f"service_contract:{contract_id}:{kind}"


def _is_sql(store: Any) -> bool:
    return hasattr(store, "db") and hasattr(store, "communication")


def _de(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def texts(contract: Any, deadline: Deadline, provider: str, tariff_label: str | None) -> tuple[str, str, str, str]:
    """(task title, notification content, severity, priority) in German, like the other reminders."""
    number = f" (Nr. {contract.contract_number})" if contract.contract_number else ""
    if deadline.kind == "notice":
        after = (f"Sonst verlängert er sich bis {_de(deadline.renews_to)}." if deadline.renews_to
                 else "Sonst läuft er unbefristet weiter.")
        return (f"Kündigungsfrist: {contract.title}",
                f"Die Kündigung muss bis {_de(deadline.day)} bei {provider} eingehen, damit der Vertrag{number} "
                f"zum {_de(deadline.end)} endet. {after}", "warning", "high")
    if deadline.kind == "price_guarantee":
        tariff = f" des Tarifs „{tariff_label}“" if tariff_label else ""
        return (f"Preisgarantie endet: {contract.title}",
                f"Die Preisgarantie{tariff} endet am {_de(deadline.day)}. Danach kann {provider} die Preise ändern; "
                "Angebote vergleichen oder Sonderkündigungsrecht prüfen.", "info", "medium")
    return (f"Vertragsende: {contract.title}",
            f"Der Vertrag{number} mit {provider} endet am {_de(deadline.day)}. Anschlussvertrag bzw. "
            "Folgeversorgung klären.", "info", "medium")


def _stage(store: Any, task: TaskCreate, notification: NotificationCreate) -> None:
    """SQL: staged in the chunk's transaction (committed with ledger and checkpoint); memory: written."""
    if _is_sql(store):
        store.communication.validate_task(task)
        store.communication._tasks.create(task)
        store.communication._notifications.create(notification)
    else:
        store.create_task(task)
        store.create_notification(notification)


def _primary_property(locations: list[Any], properties: set[str]) -> str | None:
    for location in sorted(locations, key=lambda loc: (loc.created_at, loc.id)):
        if location.property_id in properties:
            return location.property_id
    return None


def remind(unit: Any, contracts: list[Any], as_of: date, progress: dict) -> None:
    store = unit.store
    ids = [c.id for c in contracts]
    locations: dict[str, list[Any]] = defaultdict(list)
    for row in store.list_service_contract_locations(service_contract_ids=ids):
        locations[row.service_contract_id].append(row)
    tariffs: dict[str, list[Any]] = defaultdict(list)
    for row in store.list_service_contract_tariffs(service_contract_ids=ids):
        tariffs[row.service_contract_id].append(row)
    properties = {p.id for p in store.list_properties()}
    for contract in contracts:
        own_tariffs = tariffs[contract.id]
        for deadline in due_reminders(contract, own_tariffs, as_of):
            if not unit.ledger.record(rule_key(contract.id, deadline.kind), RULE_VERSION, deadline.day.isoformat(),
                                      "created", unit.run.id):
                continue          # reminded already (this or an earlier run, any worker)
            try:
                provider = provider_name(store.get_contact(contract.provider_contact_id))
            except NotFoundError:
                provider = "dem Anbieter"
            tariff = next((t for t in own_tariffs if t.id == deadline.tariff_id), None)
            title, content, severity, priority = texts(contract, deadline, provider, tariff.label if tariff else None)
            _stage(store, TaskCreate(title=title, description=content, due_date=deadline.day, priority=priority,
                                     property_id=_primary_property(locations[contract.id], properties)),
                   NotificationCreate(notification_type="service_contract_deadline", title=title, content=content,
                                      severity=severity, entity_type="service_contract", entity_id=contract.id))
            progress[deadline.kind] = progress.get(deadline.kind, 0) + 1


def make_handler(chunk: int = CHUNK):
    def handle(ctx: JobContext) -> bool:
        as_of = date.fromisoformat(ctx.run.payload["as_of"])
        after = ctx.checkpoint.get("after", "")
        progress = ctx.progress
        with ctx.unit() as unit:
            contracts = unit.store.list_service_contracts_after(after, chunk)
            if not contracts:
                unit.save({"after": after, "done": True}, progress)
                return True
            remind(unit, contracts, as_of, progress)
            progress["contracts"] = progress.get("contracts", 0) + len(contracts)
            unit.save({"after": contracts[-1].id}, progress)
        return False

    return handle
