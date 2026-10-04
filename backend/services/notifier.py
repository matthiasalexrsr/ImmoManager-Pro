"""Shared rules for generated notifications: what is still open, readable texts, no repeats."""

from datetime import date
from typing import Any, Optional

from ..models import Notification, NotificationCreate

# A receivable is unpaid until it is paid or cancelled; "overdue" is set by hand or by dunning.
UNPAID_RECEIVABLE_STATUSES = frozenset({"open", "overdue", "partial"})
# Tasks and maintenance cases still need work while they are open or in progress.
OPEN_WORK_STATUSES = frozenset({"open", "in_progress"})


def is_unpaid_debt(receivable: Any) -> bool:
    """An unpaid amount the tenant owes; credits (negative amounts) are owed to the tenant."""
    return receivable.status in UNPAID_RECEIVABLE_STATUSES and (receivable.amount_due or 0) > 0


def eur(value: Any) -> str:
    """1234.5 -> '1.234,50 €'."""
    return f"{float(value or 0):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def day(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def receivable_debtor(store: Any, receivable: Any) -> tuple[str, str]:
    """Tenant name and contract number of a receivable, with placeholders if they are gone."""
    try:
        contract = store.get_contract(receivable.contract_id)
    except Exception:
        return "Unbekannt", "—"
    try:
        tenant_name = store.get_tenant(contract.tenant_id).full_name
    except Exception:
        tenant_name = "Unbekannt"
    return tenant_name, contract.contract_number


def _key(notification: Any) -> tuple:
    return (notification.notification_type, notification.entity_type, notification.entity_id,
            notification.content)


class Notifier:
    """Creates notifications, but never the same one twice.

    A notification repeats when type, subject and text match one that exists already,
    whether it was read or not. A changed due date or amount changes the text and is
    reported again.
    """

    def __init__(self, store: Any) -> None:
        self._store = store
        self._known = {_key(n) for n in store.list_notifications()}

    def notify(self, payload: NotificationCreate) -> Optional[Notification]:
        key = _key(payload)
        if key in self._known:
            return None
        self._known.add(key)
        return self._store.create_notification(payload)
