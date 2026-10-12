"""SQL reads of the deposit file (mixed into SQLAlchemyStore); writes go through services/deposits.py.

Every read runs through the request's session, so the portfolio boundary applies
(services/portfolio_scope.py).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select

from ..db.deposit_models import (
    DepositInstalmentORM,
    DepositInterestRateORM,
    DepositPaymentORM,
    DepositSettlementItemORM,
    DepositSettlementORM,
)
from ..models_deposits import (
    DepositInstalment,
    DepositInterestRate,
    DepositPayment,
    DepositSettlement,
    DepositSettlementItem,
)


def _rows(db: Any, query: Any, model: Any) -> list:
    return [model.model_validate({column.key: getattr(row, column.key) for column in row.__table__.columns})
            for row in db.scalars(query)]


class DepositStoreMethods:
    db: Any

    def list_deposit_instalments(self, deposit_id: str | None = None) -> list[DepositInstalment]:
        query = select(DepositInstalmentORM).order_by(DepositInstalmentORM.deposit_id, DepositInstalmentORM.number)
        if deposit_id is not None:
            query = query.where(DepositInstalmentORM.deposit_id == deposit_id)
        return _rows(self.db, query, DepositInstalment)

    def list_deposit_interest_rates(self, deposit_id: str | None = None) -> list[DepositInterestRate]:
        query = select(DepositInterestRateORM).order_by(DepositInterestRateORM.deposit_id,
                                                        DepositInterestRateORM.valid_from)
        if deposit_id is not None:
            query = query.where(DepositInterestRateORM.deposit_id == deposit_id)
        return _rows(self.db, query, DepositInterestRate)

    def list_deposit_payments(self, deposit_id: str | None = None,
                              booking_ids: Iterable[str] | None = None) -> list[DepositPayment]:
        query = select(DepositPaymentORM).order_by(DepositPaymentORM.created_at, DepositPaymentORM.id)
        if deposit_id is not None:
            query = query.where(DepositPaymentORM.deposit_id == deposit_id)
        if booking_ids is not None:
            wanted = sorted(set(booking_ids))
            if not wanted:
                return []
            query = query.where(DepositPaymentORM.booking_id.in_(wanted))
        return _rows(self.db, query, DepositPayment)

    def list_deposit_settlements(self, deposit_id: str | None = None) -> list[DepositSettlement]:
        query = select(DepositSettlementORM).order_by(DepositSettlementORM.created_at, DepositSettlementORM.id)
        if deposit_id is not None:
            query = query.where(DepositSettlementORM.deposit_id == deposit_id)
        return _rows(self.db, query, DepositSettlement)

    def list_deposit_settlement_items(self, settlement_id: str | None = None) -> list[DepositSettlementItem]:
        query = select(DepositSettlementItemORM).order_by(DepositSettlementItemORM.settlement_id,
                                                          DepositSettlementItemORM.position,
                                                          DepositSettlementItemORM.id)
        if settlement_id is not None:
            query = query.where(DepositSettlementItemORM.settlement_id == settlement_id)
        return _rows(self.db, query, DepositSettlementItem)
