"""In-memory collections of the deposit file (mixed into storage.InMemoryStore).

Business rules and writes live in services/deposits.py (through document_versions.work,
which undoes a failed unit); this keeps the records and answers the reads the rest
of the application needs (rent account, deletion guard, data access export).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models_deposits import (
    DepositInstalment,
    DepositInterestRate,
    DepositPayment,
    DepositSettlement,
    DepositSettlementItem,
)


@dataclass
class DepositMemoryStore:
    deposit_instalments: Dict[str, DepositInstalment] = field(default_factory=dict)
    deposit_interest_rates: Dict[str, DepositInterestRate] = field(default_factory=dict)
    deposit_settlements: Dict[str, DepositSettlement] = field(default_factory=dict)
    deposit_settlement_items: Dict[str, DepositSettlementItem] = field(default_factory=dict)
    deposit_payments: Dict[str, DepositPayment] = field(default_factory=dict)

    def list_deposit_instalments(self, deposit_id: Optional[str] = None) -> List[DepositInstalment]:
        return sorted((row for row in self.deposit_instalments.values()
                       if deposit_id is None or row.deposit_id == deposit_id),
                      key=lambda row: (row.deposit_id, row.number))

    def list_deposit_interest_rates(self, deposit_id: Optional[str] = None) -> List[DepositInterestRate]:
        return sorted((row for row in self.deposit_interest_rates.values()
                       if deposit_id is None or row.deposit_id == deposit_id),
                      key=lambda row: (row.deposit_id, row.valid_from))

    def list_deposit_payments(self, deposit_id: Optional[str] = None,
                              booking_ids: Optional[Iterable[str]] = None) -> List[DepositPayment]:
        wanted = set(booking_ids) if booking_ids is not None else None
        return [row for row in self.deposit_payments.values()
                if (deposit_id is None or row.deposit_id == deposit_id)
                and (wanted is None or row.booking_id in wanted)]

    def list_deposit_settlements(self, deposit_id: Optional[str] = None) -> List[DepositSettlement]:
        return [row for row in self.deposit_settlements.values() if deposit_id is None or row.deposit_id == deposit_id]

    def list_deposit_settlement_items(self, settlement_id: Optional[str] = None) -> List[DepositSettlementItem]:
        return sorted((row for row in self.deposit_settlement_items.values()
                       if settlement_id is None or row.settlement_id == settlement_id),
                      key=lambda row: (row.settlement_id, row.position, row.id))
