"""A read-only view of the store for calculations over many contracts.

The review list, accounts and reports look up the contracts and the rent history
of every contract again and again (once per contract, once per payment). This
view reads both once and answers the repeated questions from memory; all bookings
come from memory as long as no booking changed. Use it only
for reading within one calculation; everything else goes to the store itself.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..concurrency import whole_table


class CachedReads:
    def __init__(self, store: Any) -> None:
        self._store = store
        self._contracts: list[Any] | None = None
        self._periods: dict[str, list[Any]] | None = None
        self._units: dict[str, Any] | None = None
        self._properties: dict[str, Any] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def list_contracts(self) -> list[Any]:
        if self._contracts is None:
            self._contracts = self._store.list_contracts()
        return list(self._contracts)

    def list_bookings(self, tenant_id: str | None = None) -> list[Any]:
        """All bookings from memory while none changed (backend.concurrency); one tenant's from the store."""
        if tenant_id is not None:
            return self._store.list_bookings(tenant_id=tenant_id)
        return whole_table("bookings", self._store.list_bookings)

    def get_unit(self, unit_id: str) -> Any:
        """A unit from one read of all units (the rent of contracts without rent history); unknown ones as before."""
        if self._units is None:
            self._units = {unit.id: unit for unit in self._store.list_units()}
        found = self._units.get(unit_id)
        return found if found is not None else self._store.get_unit(unit_id)

    def get_property(self, property_id: str) -> Any:
        """A property from one read of all properties (the federal state of due dates); unknown ones as before."""
        if self._properties is None:
            self._properties = {prop.id: prop for prop in self._store.list_properties()}
        found = self._properties.get(property_id)
        return found if found is not None else self._store.get_property(property_id)

    def list_contract_rent_periods(self, contract_id: str | None = None) -> list[Any]:
        if self._periods is None:
            grouped: dict[str, list[Any]] = defaultdict(list)
            for period in self._store.list_contract_rent_periods():   # sorted by contract and date
                grouped[period.contract_id].append(period)
            self._periods = grouped
        if contract_id is None:
            return [p for periods in self._periods.values() for p in periods]
        return list(self._periods.get(contract_id, ()))
