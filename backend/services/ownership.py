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

Owners change: a sale, gift, inheritance or division (record_transfer) ends the shares involved on
the day before and starts the new ones on its day. Money of a day follows the owners of that day;
money of a period (a month's rent, a service period, a budget year) is split by the owners' days in
it (split_period), so a sale on the 16th gives each owner their days of the month's rent.

Amounts are split to the cent by the largest remainder over all owners at once
(domain.billing_engine.allocate_cents), so the owners' parts always add up to the amount and
every report by owner adds up to the report of all owners.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException

from ..domain.billing_engine import allocate_cents
from ..domain.clock import local_today
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
        self._changes: dict[str, list[date]] = {}

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
        return self._allocate(amount, self.weights(property_id, unit_id, day))

    def part(self, owner: Optional[str], amount: Any, property_id: Optional[str], unit_id: Optional[str],
             day: date, booking_owner: Optional[str] = None) -> Decimal:
        """One owner's part (owner None: the part nobody is recorded for)."""
        return self.split(amount, property_id, unit_id, day, booking_owner).get(owner, ZERO)

    def _change_days(self, property_id: str) -> list[date]:
        """Days on which a share of the property or one of its units begins or ends (the day after)."""
        found = self._changes.get(property_id)
        if found is None:
            days: set[date] = set()
            for (prop, _unit), shares in self._shares.items():
                if prop != property_id:
                    continue
                for share in shares:
                    if share.valid_from:
                        days.add(share.valid_from)
                    if share.valid_to and share.valid_to < date.max:
                        days.add(share.valid_to + timedelta(days=1))
            found = self._changes[property_id] = sorted(days)
        return found

    def period_weights(self, property_id: Optional[str], unit_id: Optional[str], first: date,
                       last: date) -> dict[Optional[str], Decimal]:
        """Percent per owner over a period, by days: a change of owners within it counts day by day."""
        if property_id is None and unit_id:
            property_id = self._unit_property.get(unit_id)
        if property_id is None or last <= first:
            return self.weights(property_id, unit_id, first)
        inside = [day for day in self._change_days(property_id) if first < day <= last]
        if not inside:
            return self.weights(property_id, unit_id, first)
        starts = [first, *inside]
        ends = [day - timedelta(days=1) for day in inside] + [last]
        total = Decimal((last - first).days + 1)
        weights: dict[Optional[str], Decimal] = defaultdict(lambda: ZERO)
        for start, end in zip(starts, ends):
            days = Decimal((end - start).days + 1)
            for owner, percent in self.weights(property_id, unit_id, start).items():
                weights[owner] += percent * days / total
        return dict(weights)

    def _allocate(self, amount: Decimal, weights: dict[Optional[str], Decimal]) -> dict[Optional[str], Decimal]:
        owners = sorted(weights, key=lambda name: (name is None, name or ""))
        parts = allocate_cents(amount, [weights[name] for name in owners]) if amount else [ZERO] * len(owners)
        return dict(zip(owners, parts))

    def split_period(self, amount: Any, property_id: Optional[str], unit_id: Optional[str], first: date, last: date,
                     owner: Optional[str] = None) -> dict[Optional[str], Decimal]:
        """An amount of a period (a month's rent, a service period, a budget year) by the owners' days in it."""
        amount = money(amount)
        if owner:
            return {owner: amount}
        return self._allocate(amount, self.period_weights(property_id, unit_id, first, last))

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

    def period(self, amount: Any, property_id: Optional[str], unit_id: Optional[str], first: date, last: date) -> Decimal:
        """The owner's part of an amount for a period, by their days in it."""
        if self.ownership is None:
            return money(amount)
        return self.ownership.split_period(amount, property_id, unit_id, first, last).get(self.owner, ZERO)

    def contract_period(self, contract: Any, amount: Any, first: date, last: date) -> Decimal:
        """A contract's amount for its days from *first* to *last* (within its term)."""
        first = max(first, contract.start_date)
        if contract.end_date:
            last = min(last, contract.end_date)
        return self.period(amount, contract.property_id, contract.unit_id, first, max(first, last))

    def owns_between(self, property_id: Optional[str], unit_id: Optional[str], first: date, last: date) -> bool:
        """Whether the owner has a part of the property or unit on any day of a period."""
        if self.ownership is None:
            return True
        return self.ownership.period_weights(property_id, unit_id, first, last).get(self.owner, ZERO) > 0

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


def require_owner(store: Any, contact_id: Optional[str], role: str = "Der Eigentümer der Buchung") -> None:
    """A booking's or an account's owner is a contact of type "owner"."""
    if not contact_id:
        return
    try:
        contact = store.get_contact(contact_id)
    except NotFoundError:
        raise HTTPException(422, f"{role} ist nicht im Adressbuch.") from None
    if contact.contact_type != "owner":
        raise HTTPException(422, f"{role} muss ein Kontakt vom Typ „Eigentümer“ sein.")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def owner_name(contact: Any) -> str:
    person = " ".join(part for part in (contact.first_name, contact.last_name) if part)
    return contact.company_name or person or "Eigentümer"


def owners(store: Any) -> list[dict[str, Any]]:
    """Every contact of type owner (or holding a share), with the number of shares recorded for them."""
    counts: dict[str, int] = defaultdict(int)
    for share in list_shares(store):
        counts[share.owner_contact_id] += 1
    found = [{"id": contact.id, "name": owner_name(contact), "shares": counts.get(contact.id, 0)}
             for contact in store.list_contacts() if contact.contact_type == "owner" or contact.id in counts]
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


# ---------------------------------------------------------------------------
# Changes of owners: sale, gift, inheritance, division
# ---------------------------------------------------------------------------

SHARE_UNIT = Decimal("0.0001")


def _split_percent(moved: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """A percentage split by weights to 0.0001 %, the parts adding up exactly (largest remainder)."""
    units = int((moved / SHARE_UNIT).to_integral_value())
    total = sum(weights, ZERO)
    exact = [Decimal(units) * weight / total for weight in weights]
    floors = [int(value) for value in exact]
    for index in sorted(range(len(weights)), key=lambda i: (-(exact[i] - floors[i]), i))[:units - sum(floors)]:
        floors[index] += 1
    return [Decimal(value) * SHARE_UNIT for value in floors]


def _owner_contact(store: Any, contact_id: str, role: str) -> Any:
    try:
        contact = store.get_contact(contact_id)
    except NotFoundError:
        raise HTTPException(422, f"{role} ist nicht im Adressbuch.") from None
    if contact.contact_type != "owner":
        raise HTTPException(422, f"{role} ist kein Kontakt vom Typ „Eigentümer“.")
    return contact


def record_transfer(store: Any, data: Any, actor_id: Optional[str]) -> Any:
    """Record a change of owners on a day, in one step.

    For every object the change covers (the chosen property or unit, or with scope "all" every
    property and unit the giver holds a share of on that day): the giver's share ends on the day
    before and their rest, if any, continues from the day; the part that changes hands goes to the
    receivers by their percentages. A receiver who already holds a share of the object gets one
    share of the sum from the day. Shares that begin on that very day are replaced, so several
    changes on one day (two heirs passing to one) add up. The sum of the shares stays as it was.
    """
    from uuid import uuid4

    from ..models_ownership import TRANSFER_KINDS, OwnershipTransfer
    from .maintenance_projects import work
    from .maintenance_rows import stamp

    day = data.effective_date
    with work(store, actor_id, AREAS) as unit_of_work:
        rows, target = Rows.of(unit_of_work), unit_of_work.store
        giver = _owner_contact(target, data.from_owner_contact_id, "Der Abgebende")
        receivers = [_owner_contact(target, r.owner_contact_id, "Ein Empfänger") for r in data.receivers]
        try:
            prop = target.get_property(data.property_id)
            unit = target.get_unit(data.unit_id) if data.unit_id else None
        except NotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        if unit is not None and unit.property_id != prop.id:
            raise HTTPException(422, "Die Einheit gehört nicht zu diesem Objekt.")
        labels = {u.id: u.label for u in target.list_units() if u.property_id == prop.id}

        def place(obj: Optional[str]) -> str:
            return f"„{labels.get(obj, 'Einheit')}“" if obj else f"„{prop.name}“ (ganzes Objekt)"

        shares = rows.find("ownership_shares", property_id=prop.id)
        if data.scope == "all":
            objects = sorted({s.unit_id for s in shares if s.owner_contact_id == giver.id and active_on(s, day)},
                             key=lambda obj: (obj is not None, labels.get(obj or "", "")))
            if not objects:
                raise HTTPException(409, f"{owner_name(giver)} hält am {day:%d.%m.%Y} keinen Anteil an „{prop.name}“.")
        else:
            objects = [data.unit_id]
        involved = {giver.id, *(r.id for r in receivers)}
        kind = TRANSFER_KINDS[data.kind]
        now = stamp("ownership_shares")
        # what the change does to the shares, kept in the journal so that it can be undone (revert_transfer)
        changes: dict[str, list] = {"ended": [], "removed": [], "created": []}

        def close(share: Any) -> None:
            if (share.valid_from or date.min) < day:
                changes["ended"].append({"id": share.id, "valid_to": share.valid_to.isoformat() if share.valid_to else None})
                rows.update("ownership_shares", share.id, valid_to=day - timedelta(days=1))
            else:
                changes["removed"].append(share.model_dump(mode="json"))
                rows.delete("ownership_shares", share.id)

        def open_share(owner: str, obj: Optional[str], percent: Decimal, note: Optional[str]) -> None:
            created = OwnershipShare(
                id=str(uuid4()), owner_contact_id=owner, property_id=prop.id, unit_id=obj,
                share_percent=float(percent), valid_from=day, valid_to=None, note=note, created_at=now, updated_at=now)
            changes["created"].append(created.model_dump(mode="json"))
            rows.add("ownership_shares", created)

        for obj in objects:
            own = [s for s in shares if s.unit_id == obj]
            held = [s for s in own if s.owner_contact_id == giver.id and active_on(s, day)]
            if not held:
                raise HTTPException(409, f"{owner_name(giver)} hält am {day:%d.%m.%Y} keinen Anteil an {place(obj)}."
                                    + ("" if obj or data.scope == "all" else " Gehören ihm Einheiten, bitte „Alle Anteile am Objekt“ wählen."))
            if any((s.valid_from or date.min) > day for s in own):
                raise HTTPException(409, f"An {place(obj)} ist nach dem {day:%d.%m.%Y} schon ein Wechsel erfasst. "
                                         "Bitte die Wechsel der Reihe nach erfassen.")
            if any(s.owner_contact_id in involved and active_on(s, day) and s.valid_to is not None for s in own):
                raise HTTPException(409, f"Ein beteiligter Anteil an {place(obj)} hat ein festes Ende. Bitte das Ende zuerst entfernen.")
            share = held[0]
            current = _percent(share.share_percent)
            moved = (current * Decimal(str(data.fraction_percent)) / HUNDRED).quantize(SHARE_UNIT)
            if moved <= 0:
                raise HTTPException(422, "Der übertragene Teil ist kleiner als 0,0001 %.")
            close(share)
            if current - moved > 0:
                open_share(giver.id, obj, current - moved, share.note)
            parts = _split_percent(moved, [Decimal(str(r.percent)) for r in data.receivers]) if data.receivers else []
            for receiver, part in zip(receivers, parts):
                existing = next((s for s in own if s.owner_contact_id == receiver.id and active_on(s, day)), None)
                note = f"{kind} von {owner_name(giver)} am {day:%d.%m.%Y}"
                if existing is not None:
                    close(existing)
                    part += _percent(existing.share_percent)
                    note = f"{existing.note}; {note}" if existing.note else note
                open_share(receiver.id, obj, part, note)
        record = OwnershipTransfer(
            id=str(uuid4()), property_id=prop.id, unit_id=data.unit_id, scope=data.scope, effective_date=day,
            from_owner_contact_id=giver.id, fraction_percent=data.fraction_percent, kind=data.kind,
            receivers=[{"owner_contact_id": r.owner_contact_id, "percent": r.percent} for r in data.receivers],
            note=data.note, actor_id=actor_id, created_at=now, changes=changes)
        rows.add("ownership_transfers", record)
        return record


SHARE_FIELDS = ("owner_contact_id", "property_id", "unit_id", "share_percent", "valid_from", "valid_to", "note")


def revert_transfer(store: Any, transfer_id: str, actor_id: Optional[str]) -> Any:
    """Undo the latest owner change of a property: the shares are as before it, the journal keeps it.

    Only the latest change that is not undone yet, and only while the shares it ended and created
    are as it left them; otherwise the shares are corrected by hand.
    """
    from .maintenance_projects import work
    from .maintenance_rows import stamp

    with work(store, actor_id, AREAS) as unit_of_work:
        rows = Rows.of(unit_of_work)
        transfer = rows.require("ownership_transfers", transfer_id, "Eigentümerwechsel nicht gefunden")
        if transfer.reverted_at:
            raise HTTPException(409, "Dieser Eigentümerwechsel ist schon rückgängig gemacht.")
        if not transfer.changes:
            raise HTTPException(409, "Dieser Eigentümerwechsel wurde vor dieser Version erfasst und lässt sich nicht "
                                     "automatisch rückgängig machen. Bitte die Anteile von Hand korrigieren.")
        later = [t for t in rows.find("ownership_transfers", property_id=transfer.property_id)
                 if not t.reverted_at and t.id != transfer.id and str(t.created_at) > str(transfer.created_at)]
        if later:
            raise HTTPException(409, "Nach diesem Wechsel ist am Objekt schon ein weiterer erfasst. Bitte zuerst den "
                                     "letzten Wechsel rückgängig machen.")
        day = transfer.effective_date
        current = {share.id: share for share in rows.find("ownership_shares", property_id=transfer.property_id)}

        def unchanged(snapshot: dict) -> bool:
            share = current.get(snapshot["id"])
            if share is None:
                return False
            now = share.model_dump(mode="json")
            return all(now[key] == snapshot[key] for key in SHARE_FIELDS)

        ended_ok = all(entry["id"] in current and current[entry["id"]].valid_to == day - timedelta(days=1)
                       for entry in transfer.changes["ended"])
        if not ended_ok or not all(unchanged(snapshot) for snapshot in transfer.changes["created"]):
            raise HTTPException(409, "Die Anteile wurden seit dem Wechsel von Hand geändert. Bitte die Anteile von Hand "
                                     "korrigieren.")
        for snapshot in transfer.changes["created"]:
            rows.delete("ownership_shares", snapshot["id"])
        for entry in transfer.changes["ended"]:
            rows.update("ownership_shares", entry["id"],
                        valid_to=date.fromisoformat(entry["valid_to"]) if entry["valid_to"] else None)
        for snapshot in transfer.changes["removed"]:
            rows.add("ownership_shares", OwnershipShare(**snapshot))
        return rows.update("ownership_transfers", transfer.id, reverted_at=stamp("ownership_transfers"),
                           reverted_by=actor_id)


def _described(weights: dict[Optional[str], Decimal], names: dict[str, str]) -> list[dict[str, Any]]:
    rows = [{"owner_contact_id": owner, "name": names.get(owner, "Eigentümer") if owner else "Ohne Eigentümer",
             "percent": float(round(percent, 4))} for owner, percent in weights.items() if percent > 0]
    return sorted(rows, key=lambda row: (row["owner_contact_id"] is None, -row["percent"], row["name"]))


def history(store: Any, property_id: str) -> dict[str, Any]:
    """Who owned the property and each unit when: periods between changes, and the journal of changes."""
    from ..models_ownership import TRANSFER_KINDS

    prop = store.get_property(property_id)
    names = {contact.id: owner_name(contact) for contact in store.list_contacts()}
    ownership = Ownership(store)
    days = ownership._change_days(prop.id)
    units = sorted((u for u in store.list_units() if u.property_id == prop.id), key=lambda u: u.label or "")

    def periods(unit_id: Optional[str]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        starts: list[Optional[date]] = [None, *days]
        for index, start in enumerate(starts):
            end = days[index] - timedelta(days=1) if index < len(days) else None
            probe = start or (days[0] - timedelta(days=1) if days else local_today())
            owners = _described(ownership.weights(prop.id, unit_id, probe), names)
            if found and found[-1]["owners"] == owners:
                found[-1]["to"] = end.isoformat() if end else None
                continue
            found.append({"from": start.isoformat() if start else None, "to": end.isoformat() if end else None,
                          "owners": owners})
        return found

    journal = sorted(Rows.reading(store).find("ownership_transfers", property_id=prop.id),
                     key=lambda t: (t.effective_date, str(t.created_at)))
    in_force = sorted((t for t in journal if not t.reverted_at), key=lambda t: str(t.created_at))
    latest = in_force[-1].id if in_force else None
    return {
        "property_id": prop.id,
        "objects": [{"unit_id": None, "label": "Ganzes Objekt", "periods": periods(None)},
                    *({"unit_id": u.id, "label": u.label, "periods": periods(u.id)} for u in units)],
        "transfers": [{**t.model_dump(mode="json", exclude={"changes"}), "kind_label": TRANSFER_KINDS.get(t.kind, t.kind),
                       # only the latest change still in force can be undone (revert_transfer)
                       "revertible": t.id == latest and bool(t.changes),
                       "from_name": names.get(t.from_owner_contact_id, "Eigentümer"),
                       "unit_label": next((u.label for u in units if u.id == t.unit_id), None),
                       "receivers": [{**r, "name": names.get(r["owner_contact_id"], "Eigentümer")} for r in t.receivers]}
                      for t in journal],
    }


# ---------------------------------------------------------------------------
# Account balances by owner
# ---------------------------------------------------------------------------

def owner_balances(store: Any, as_of: date, portfolio_id: Optional[str] = None) -> dict[str, Any]:
    """Each owner's part of the account balances on a day, per account.

    An owner's part: the opening balances of the accounts they hold alone and their part of every
    booking up to the day (the same split as the reports). The rows, "Ohne Eigentümer" included,
    add up to each account's balance to the cent.
    """
    from ..domain.money import as_number
    from .finance_ledger import FinanceFilter, booking_totals

    accounts = {a.id: a for a in store.list_accounts() if not portfolio_id or a.portfolio_id == portfolio_id}
    names = {contact.id: owner_name(contact) for contact in store.list_contacts()}
    keys = [contact.id for contact in store.list_contacts() if contact.contact_type == "owner"]
    keys += sorted({a.owner_contact_id for a in accounts.values() if getattr(a, "owner_contact_id", None)} - set(keys))
    whole: dict[str, Decimal] = defaultdict(lambda: ZERO)
    rows = []
    for key in [*keys, NOBODY]:
        flt = FinanceFilter(portfolio_id=portfolio_id, owner_contact_id=key).with_period(None, as_of)
        per_account: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for account in flt.opening_accounts(store):
            per_account[account.id] += money(account.opening_balance)
        for total in booking_totals(store, flt, by=("account",)):
            if total.account_id and total.account_id in accounts:
                per_account[total.account_id] += total.amount
        if not any(per_account.values()):
            continue
        for account_id, value in per_account.items():
            whole[account_id] += value
        rows.append({"owner_contact_id": key, "name": "Ohne Eigentümer" if key == NOBODY else names.get(key, "Eigentümer"),
                     "balance": as_number(sum(per_account.values(), ZERO)),
                     "accounts": [{"account_id": account_id, "name": accounts[account_id].name, "balance": as_number(value)}
                                  for account_id, value in sorted(per_account.items(), key=lambda item: accounts[item[0]].name)
                                  if value]})
    rows.sort(key=lambda row: (row["owner_contact_id"] == NOBODY, row["name"].lower()))
    return {"as_of": as_of.isoformat(), "owners": rows,
            "accounts": [{"account_id": a.id, "name": a.name, "balance": as_number(whole.get(a.id, ZERO))}
                         for a in sorted(accounts.values(), key=lambda a: a.name)]}
