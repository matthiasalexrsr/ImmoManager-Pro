"""The tenant account of a contract as it is kept in this app.

A running tenancy taken over from a previous system keeps its account here from
``ledger_start`` on (the first of a month): the months before were settled there.
The account's balance on that day (``carried_balance``) comes along: arrears as
the oldest claim, a credit as a payment on that day. Payments booked before the
day belong to the carried balance and are not credited again (payment_allocations).

Accounts, the rent overview, dunning and deposit settlements use this. Reports of
rent due per month do not: the rent was owed in those months all the same.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ..domain.lease_engine import LeaseEngine, PaymentLine, ReceivableLine, RentStep
from ..domain.money import ZERO, money
from .rent_history import rent_steps

CARRIED_LABEL = "Rückstand zum Übernahmetag"


def takeover(contract: Any) -> tuple[date | None, Decimal]:
    """(first day kept here, balance carried over) of a taken-over tenancy, else (None, 0)."""
    start = getattr(contract, "ledger_start", None)
    if start is None or start <= contract.start_date:
        return None, ZERO
    return start, money(getattr(contract, "carried_balance", None) or 0)


def account_receivables(store: Any, contract: Any, until: date,
                        steps: list[RentStep] | None = None) -> list[ReceivableLine]:
    """What the tenant owes on this contract's account up to *until*, oldest first."""
    lines = LeaseEngine.build_monthly_receivables(
        contract_start=contract.start_date, contract_end=contract.end_date,
        rent_steps=rent_steps(store, contract) if steps is None else steps, until_including=until)
    start, carried = takeover(contract)
    if start is None:
        return lines
    lines = [line for line in lines if line.period_start >= start]
    day = start - timedelta(days=1)
    if carried > 0 and start <= until:
        lines.insert(0, ReceivableLine(period_start=day, period_end=start, due_date=day, cold_rent=ZERO,
                                       service_charge_advance=ZERO, heating_advance=ZERO,
                                       total_amount=carried, label=CARRIED_LABEL))
    return lines


def carried_credit(contract: Any, until: date | None) -> list[PaymentLine]:
    """The tenant's credit carried over, as a payment on the takeover day."""
    start, carried = takeover(contract)
    if start is None or carried >= 0 or (until is not None and start > until):
        return []
    return [PaymentLine(booking_date=start, amount=-carried)]
