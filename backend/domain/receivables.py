"""What counts as unpaid, overdue or a credit among receivables.

A receivable stays unpaid until it is paid or cancelled; "overdue" is set by
hand or by dunning, but any unpaid debt past its due date is overdue too. A
negative amount is a credit the landlord owes the tenant (e.g. the refund of a
utility statement), so it never adds to what tenants owe.
"""

from datetime import date
from typing import Any

UNPAID_RECEIVABLE_STATUSES = frozenset({"open", "overdue", "partial"})


def is_unpaid_debt(receivable: Any) -> bool:
    return receivable.status in UNPAID_RECEIVABLE_STATUSES and (receivable.amount_due or 0) > 0


def is_open_credit(receivable: Any) -> bool:
    return receivable.status in UNPAID_RECEIVABLE_STATUSES and (receivable.amount_due or 0) < 0


def is_overdue_debt(receivable: Any, today: date) -> bool:
    return is_unpaid_debt(receivable) and (receivable.status == "overdue" or receivable.due_date < today)
