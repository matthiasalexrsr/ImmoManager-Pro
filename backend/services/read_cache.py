"""A read-only view of the store for calculations over many contracts.

The review list, accounts and reports look up the contracts and the rent history
of every contract again and again (once per contract, once per payment). This
view reads both once and answers the repeated questions from memory. Use it only
for reading within one calculation; everything else goes to the store itself.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class CachedReads:
    def __init__(self, store: Any) -> None:
        self._store = store
        self._contracts: list[Any] | None = None
        self._periods: dict[str, list[Any]] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def list_contracts(self) -> list[Any]:
        if self._contracts is None:
            self._contracts = self._store.list_contracts()
        return list(self._contracts)

    def list_contract_rent_periods(self, contract_id: str | None = None) -> list[Any]:
        if self._periods is None:
            grouped: dict[str, list[Any]] = defaultdict(list)
            for period in self._store.list_contract_rent_periods():   # sorted by contract and date
                grouped[period.contract_id].append(period)
            self._periods = grouped
        if contract_id is None:
            return [p for periods in self._periods.values() for p in periods]
        return list(self._periods.get(contract_id, ()))
