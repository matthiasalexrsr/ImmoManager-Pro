"""The same write boundary and interval rules for shares, changes and imports."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

# One transaction key deliberately covers moves between properties and snapshot
# imports as well. Lock it before reading shares or taking import table locks.
OWNERSHIP_LOCK = 0x494D4D4F4F574E52


def lock_ownership(db: Any) -> None:
    if db is not None and db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": OWNERSHIP_LOCK})
    # SQLite writers already hold BEGIN IMMEDIATE; memory writers hold the
    # archive's shared reentrant lock until their unit has committed/rolled back.


def problems(shares: list, contacts: dict, properties: dict, units: dict) -> list[str]:
    """Validate the complete proposed state, including inclusive interval ends."""
    errors: list[str] = []
    groups: dict[tuple, list] = defaultdict(list)
    for share in shares:
        contact = contacts.get(share.owner_contact_id)
        unit = units.get(share.unit_id) if share.unit_id else None
        prefix = f"Eigentumsanteil {share.id}: "
        if contact is None or contact.contact_type != "owner":
            errors.append(prefix + "Der Kontakt muss ein erfasster Eigentümer sein.")
        if share.property_id not in properties:
            errors.append(prefix + "Das Objekt fehlt.")
        if share.unit_id and (unit is None or unit.property_id != share.property_id):
            errors.append(prefix + "Die Einheit gehört nicht zum angegebenen Objekt.")
        if Decimal(str(share.share_percent)) <= 0:
            errors.append(prefix + "Der Anteil muss größer als null sein.")
        groups[(share.property_id, share.unit_id)].append(share)
    for (property_id, unit_id), group in groups.items():
        events: dict[date, list] = defaultdict(list)
        for share in group:
            amount = Decimal(str(share.share_percent))
            events[share.valid_from or date.min].append((amount, share.owner_contact_id, 1))
            if share.valid_to and share.valid_to < date.max:
                events[share.valid_to + timedelta(days=1)].append((-amount, share.owner_contact_id, -1))
        total = Decimal(0)
        active: dict[str, int] = defaultdict(int)
        for day in sorted(events):
            for amount, owner, count in events[day]:
                total += amount
                active[owner] += count
            label = unit_id or property_id
            when = "" if day == date.min else f" am {day:%d.%m.%Y}"
            if total > 100:
                errors.append(f"Eigentum {label}: Die Anteile ergäben{when} mehr als 100 %.")
                break
            if any(count > 1 for count in active.values()):
                errors.append(f"Eigentum {label}: Ein Eigentümer hat{when} überlappende Anteile.")
                break
    return errors
