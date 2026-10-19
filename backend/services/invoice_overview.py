"""Invoice list facts derived from the same evidence as the invoice file.

Legacy manual payment flags are preserved, but never turned into fictitious
payments. Unknown residuals remain unknown until a payment is linked.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from ..domain.money import ZERO, as_number, money
from .invoice_review import settlements
from .maintenance_rows import Rows


def overview(store: Any, invoices: Iterable[Any], *, today: date | None = None) -> list[dict]:
    invoices = list(invoices)
    today = today or date.today()
    balances = settlements(Rows.reading(store), invoices, today)
    result = []
    for invoice in invoices:
        balance = balances[invoice.id]
        paid = balance.paid
        remaining: Decimal | None = balance.open
        note: str | None = None
        if invoice.status == "cancelled":
            state, remaining = "cancelled", ZERO
            if paid:
                note = "Trotz Storno sind Zahlungen zugeordnet. Bitte in der Rechnungsakte prüfen."
        elif balance.status == "legacy":
            if not paid and invoice.status in ("paid", "partial"):
                state, remaining = invoice.status, None
                note = "Manueller Zahlungsstatus ohne zugeordnete Zahlung; Restbetrag nicht nachgewiesen."
            else:
                remaining = max(money(invoice.gross_amount) - paid, ZERO)
                state = "overpaid" if paid > money(invoice.gross_amount) else (
                    "paid" if remaining == ZERO else "partial" if paid > ZERO else "open")
        elif balance.payment_status == "not_payable":
            state, remaining = "awaiting_review", None
            note = "Noch nicht freigegeben. Zahlungsbetrag in der Rechnungsprüfung klären."
        else:
            state = {"partially_paid": "partial"}.get(balance.payment_status, balance.payment_status)
        due = balance.due_on
        overdue = bool(remaining is not None and remaining > ZERO and due and due < today)
        if overdue:
            state = "overdue"
        result.append({**invoice.model_dump(mode="json"), "payment_summary": {
            "status": state, "review_status": balance.status, "paid": as_number(paid),
            "open": None if remaining is None else as_number(remaining),
            "due_on": due.isoformat() if due else None, "overdue": overdue, "note": note,
        }})
    return result
