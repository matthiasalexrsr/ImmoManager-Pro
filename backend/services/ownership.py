"""Who owns a property or a unit, and how an amount is split among its owners.

An owner is a contact of type "owner". A share names a property and, optionally, one of its
units, a percentage and a period (both days included; open ends: since always, until further
notice). On any day the shares of one property or unit add up to at most 100 %; the rest
belongs to nobody recorded ("ohne Eigentümer", the review list names it).

Which shares an amount follows (on its day):
- a booking that names an owner (``owner_contact_id``) belongs to that owner alone, e.g. a
  withdrawal;
- money of a unit: the unit's own shares, else the shares of its property;
- money of the property as a whole (no unit, e.g. building insurance): the property's shares;
  without them the units' owners by the units' living area (all areas known), else equally per
  unit;
- money of neither (an account's own bookings): nobody recorded.

Amounts are split to the cent by the largest remainder over all owners at once
(domain.billing_engine.allocate_cents), so the owners' parts always add up to the amount and
every report by owner adds up to the report of all owners.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException

from ..domain.billing_engine import allocate_cents
from ..domain.money import ZERO, money
from ..models_ownership import OwnershipShare, OwnershipShareCreate
from ..storage import NotFoundError
from .maintenance_rows import Rows

HUNDRED = Decimal(100)
NOBODY = "none"          # filter value for the part no owner is recorded for
AREAS = ("/ownership-shares",)


def _percent(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def active_on(share: Any, day: date) -> bool:
    return (share.valid_from is None or share.valid_from <= day) and (share.valid_to is None or day <= share.valid_to)


def owner_key(value: Optional[str]) -> Optional[str]:
    """The key of a filter value among the parts of a split: None for the unowned part."""
    return None if value == NOBODY else value


class Ownership:
    """The shares of every visible property and unit, read once per calculation."""

    def __init__(self, store: Any, shares: Optional[list] = None, units: Optional[list] = None) -> None:
        shares = Rows.reading(store).find("ownership_shares") if shares is None else shares
        self.recorded = bool(shares)
        self._shares: dict[tuple[str, Optional[str]], list] = defaultdict(list)
        for share in shares:
            self._shares[(share.property_id, share.unit_id)].append(share)
        self._units: dict[str, list] = defaultdict(list)
        self._unit_property: dict[str, str] = {}
        for unit in sorted(store.list_units() if units is None else units, key=lambda u: u.id):
            self._units[unit.property_id].append(unit)
            self._unit_property[unit.id] = unit.property_id
        self._cache: dict[tuple, dict[Optional[str], Decimal]] = {}

    def _direct(self, property_id: str, unit_id: Optional[str], day: date) -> Optional[dict[Optional[str], Decimal]]:
        active = [share for share in self._shares.get((property_id, unit_id), ()) if active_on(share, day)]
        if not active:
            return None
        weights: dict[Optional[str], Decimal] = defaultdict(lambda: ZERO)
        for share in active:
            weights[share.owner_contact_id] += _percent(share.share_percent)
        rest = HUNDRED - sum(weights.values(), ZERO)
        if rest > 0:
            weights[None] += rest
        return dict(weights)

    def _by_units(self, property_id: str, day: date) -> dict[Optional[str], Decimal]:
        units = self._units.get(property_id, [])
        if not units:
            return {None: HUNDRED}
        areas = [unit.area_sqm for unit in units]
        keys = [Decimal(str(area)) for area in areas] if all(areas) else [Decimal(1)] * len(units)
        total = sum(keys, ZERO)
        weights: dict[Optional[str], Decimal] = defaultdict(lambda: ZERO)
        for unit, key in zip(units, keys):
            for owner, percent in (self._direct(property_id, unit.id, day) or {None: HUNDRED}).items():
                weights[owner] += percent * key / total
        return dict(weights)

    def weights(self, property_id: Optional[str], unit_id: Optional[str], day: date) -> dict[Optional[str], Decimal]:
        """Percent per owner (None: nobody recorded) of a property or unit on a day; adds up to 100."""
        if property_id is None and unit_id:
            property_id = self._unit_property.get(unit_id)
        key = (property_id, unit_id, day)
        found = self._cache.get(key)
        if found is None:
            if property_id is None:
                found = {None: HUNDRED}
            elif unit_id:
                found = self._direct(property_id, unit_id, day) or self._direct(property_id, None, day) or {None: HUNDRED}
            else:
                found = self._direct(property_id, None, day) or self._by_units(property_id, day)
            self._cache[key] = found
        return found

    def split(self, amount: Any, property_id: Optional[str], unit_id: Optional[str], day: date,
              owner: Optional[str] = None) -> dict[Optional[str], Decimal]:
        """The amount's part per owner, to the cent; the parts add up to the amount."""
        amount = money(amount)
        if owner:
            return {owner: amount}
        weights = self.weights(property_id, unit_id, day)
        owners = sorted(weights, key=lambda name: (name is None, name or ""))
        parts = allocate_cents(amount, [weights[name] for name in owners]) if amount else [ZERO] * len(owners)
        return dict(zip(owners, parts))

    def part(self, owner: Optional[str], amount: Any, property_id: Optional[str], unit_id: Optional[str],
             day: date, booking_owner: Optional[str] = None) -> Decimal:
        """One owner's part (owner None: the part nobody is recorded for)."""
        return self.split(amount, property_id, unit_id, day, booking_owner).get(owner, ZERO)

    def booking_split(self, booking: Any, amount: Any = None) -> dict[Optional[str], Decimal]:
        return self.split(booking.amount if amount is None else amount, booking.property_id, booking.unit_id,
                          booking.booking_date, getattr(booking, "owner_contact_id", None))

    def has_shares(self, property_id: str) -> bool:
        """Whether any share names the property or one of its units."""
        return any(key[0] == property_id for key in self._shares)

    def owns(self, owner: Optional[str], property_id: Optional[str], unit_id: Optional[str], day: date) -> bool:
        return self.weights(property_id, unit_id, day).get(owner, ZERO) > 0


class OwnerView:
    """The filter's owner: their part of an amount; without an owner in the filter the whole amount.

    One instance per calculation reads the shares once; a report applies it to every amount it
    adds (rent due, bookings, claims, invoices, …) on the amount's own day.
    """

    def __init__(self, store: Any, flt: Any) -> None:
        owner = getattr(flt, "owner_contact_id", None)
        self.active = bool(owner)
        self.owner = owner_key(owner)
        self.ownership = Ownership(store) if self.active else None

    def part(self, amount: Any, property_id: Optional[str], unit_id: Optional[str], day: date,
             booking_owner: Optional[str] = None) -> Decimal:
        if self.ownership is None:
            return money(amount)
        return self.ownership.part(self.owner, amount, property_id, unit_id, day, booking_owner)

    def booking(self, booking: Any, amount: Any = None) -> Decimal:
        return self.part(booking.amount if amount is None else amount, booking.property_id, booking.unit_id,
                         booking.booking_date, getattr(booking, "owner_contact_id", None))

    def contract(self, contract: Any, amount: Any, day: date) -> Decimal:
        return self.part(amount, contract.property_id, contract.unit_id, day)

    def owns(self, property_id: Optional[str], unit_id: Optional[str], day: date) -> bool:
        """Whether the owner has a part of the property or unit (always without an owner filter)."""
        if self.ownership is None:
            return True
        return self.ownership.owns(self.owner, property_id, unit_id, day)


# ---------------------------------------------------------------------------
# Recording shares
# ---------------------------------------------------------------------------

def _overlap(a: Any, b: Any) -> bool:
    return ((a.valid_from or date.min) <= (b.valid_to or date.max)) and ((b.valid_from or date.min) <= (a.valid_to or date.max))


def _check(rows: Rows, store: Any, data: OwnershipShareCreate, share_id: Optional[str]) -> None:
    try:
        contact = store.get_contact(data.owner_contact_id)
    except NotFoundError:
        raise HTTPException(422, "Der Eigentümer ist nicht im Adressbuch.") from None
    if contact.contact_type != "owner":
        raise HTTPException(422, "Bitte einen Kontakt vom Typ „Eigentümer“ wählen.")
    try:
        store.get_property(data.property_id)
        unit = store.get_unit(data.unit_id) if data.unit_id else None
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if unit is not None and unit.property_id != data.property_id:
        raise HTTPException(422, "Die Einheit gehört nicht zu diesem Objekt.")
    others = [share for share in rows.find("ownership_shares", property_id=data.property_id, unit_id=data.unit_id)
              if share.id != share_id and _overlap(share, data)]
    if any(share.owner_contact_id == data.owner_contact_id for share in others):
        raise HTTPException(409, "Dieser Eigentümer hat im gewählten Zeitraum schon einen Anteil an "
                                 + ("dieser Einheit." if data.unit_id else "diesem Objekt."))
    # the sum changes only where a share begins: checking each beginning finds its highest value
    start, end = data.valid_from or date.min, data.valid_to or date.max
    days = {start} | {share.valid_from for share in others if share.valid_from and start <= share.valid_from <= end}
    for day in sorted(days):
        total = _percent(data.share_percent) + sum((_percent(s.share_percent) for s in others if active_on(s, day)), ZERO)
        if total > HUNDRED:
            when = "" if day == date.min else f" am {day:%d.%m.%Y}"
            raise HTTPException(409, f"Die Anteile ergäben{when} zusammen {str(total).rstrip('0').rstrip('.').replace('.', ',')} %; "
                                     "mehr als 100 % sind nicht möglich.")


def list_shares(store: Any, *, property_id: Optional[str] = None, unit_id: Optional[str] = None,
                owner_contact_id: Optional[str] = None) -> list[OwnershipShare]:
    criteria = {key: value for key, value in (("property_id", property_id), ("unit_id", unit_id),
                                               ("owner_contact_id", owner_contact_id)) if value}
    return Rows.reading(store).find("ownership_shares", **criteria)


def create_share(store: Any, data: OwnershipShareCreate, actor_id: Optional[str]) -> OwnershipShare:
    from uuid import uuid4

    from .maintenance_projects import work
    from .maintenance_rows import stamp

    with work(store, actor_id, AREAS) as unit:
        rows = Rows.of(unit)
        _check(rows, unit.store, data, None)
        now = stamp("ownership_shares")
        record = OwnershipShare(id=str(uuid4()), **data.model_dump(), created_at=now, updated_at=now)
        rows.add("ownership_shares", record)
        return record


def update_share(store: Any, share_id: str, data: OwnershipShareCreate, actor_id: Optional[str]) -> OwnershipShare:
    from .maintenance_projects import work

    with work(store, actor_id, AREAS) as unit:
        rows = Rows.of(unit)
        rows.require("ownership_shares", share_id, "Eigentumsanteil nicht gefunden")
        _check(rows, unit.store, data, share_id)
        return rows.update("ownership_shares", share_id, **data.model_dump())


def delete_share(store: Any, share_id: str, actor_id: Optional[str]) -> None:
    from .maintenance_projects import work

    with work(store, actor_id, AREAS) as unit:
        rows = Rows.of(unit)
        rows.require("ownership_shares", share_id, "Eigentumsanteil nicht gefunden")
        rows.delete("ownership_shares", share_id)


def require_owner(store: Any, contact_id: Optional[str]) -> None:
    """A booking's owner is a contact of type "owner"."""
    if not contact_id:
        return
    try:
        contact = store.get_contact(contact_id)
    except NotFoundError:
        raise HTTPException(422, "Der Eigentümer der Buchung ist nicht im Adressbuch.") from None
    if contact.contact_type != "owner":
        raise HTTPException(422, "Eine Buchung gehört nur einem Kontakt vom Typ „Eigentümer“.")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def owner_name(contact: Any) -> str:
    person = " ".join(part for part in (contact.first_name, contact.last_name) if part)
    return contact.company_name or person or "Eigentümer"


def owners(store: Any) -> list[dict[str, Any]]:
    """Every contact of type owner, with the number of shares recorded for them."""
    counts: dict[str, int] = defaultdict(int)
    for share in list_shares(store):
        counts[share.owner_contact_id] += 1
    found = [{"id": contact.id, "name": owner_name(contact), "shares": counts.get(contact.id, 0)}
             for contact in store.list_contacts() if contact.contact_type == "owner"]
    return sorted(found, key=lambda owner: (owner["name"].lower(), owner["id"]))


def overview(store: Any, property_id: str, day: date) -> dict[str, Any]:
    """Who owns the property and each of its units on a day, as the reports split their money."""
    prop = store.get_property(property_id)
    names = {contact.id: owner_name(contact) for contact in store.list_contacts()}
    ownership = Ownership(store)

    def described(weights: dict[Optional[str], Decimal]) -> list[dict[str, Any]]:
        rows = [{"owner_contact_id": owner, "name": names.get(owner, "Ohne Eigentümer") if owner else "Ohne Eigentümer",
                 "percent": float(round(percent, 4))} for owner, percent in weights.items()]
        return sorted(rows, key=lambda row: (row["owner_contact_id"] is None, -row["percent"], row["name"]))

    units = sorted((u for u in store.list_units() if u.property_id == prop.id), key=lambda u: u.label or "")
    own = ownership._direct(prop.id, None, day)
    areas = [unit.area_sqm for unit in units]
    common_basis = "property" if own else ("area" if units and all(areas) else "units" if units else "none")
    return {
        "property_id": prop.id,
        "as_of": day.isoformat(),
        "common": described(ownership.weights(prop.id, None, day)),
        "common_basis": common_basis,
        "units": [{"unit_id": unit.id, "label": unit.label,
                   "basis": "unit" if ownership._direct(prop.id, unit.id, day) else ("property" if own else "none"),
                   "owners": described(ownership.weights(prop.id, unit.id, day))} for unit in units],
    }
