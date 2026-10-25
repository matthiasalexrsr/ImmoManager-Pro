"""Who may change what: write access by role and area of the API.

Reading is open to every signed-in user. For writing:
- eigentuemer   everything
- verwalter     everything except restoring, importing and bulk deleting data
- buchhaltung   money: bookings, accounts, invoices, receivables, deposits, budgets,
                costs of the utility statement, dunning (runs, letters, outbox, replies, blocks,
                results), bills/payments/cost transfers of
                service contracts
- techniker     building: maintenance, meters, handover protocols; in the project file of a
                maintenance case: plan, record quotes and change orders, write and finalize
                protocols, but not award or cancel orders, decide change orders or link invoices
- (buchhaltung also links invoices to the orders of a maintenance case)
- invoice review (/invoices/{id}/review): buchhaltung records the receipt, checks the
  arithmetic, decides within the four-eyes limit, settles disputes and transfers costs, but
  does not confirm the factual check; techniker confirms the factual check (for invoices of a
  maintenance order only, checked by the service) and nothing else of the review; the
  settings (four-eyes limit) belong to eigentuemer and verwalter
- readonly      only personal settings (and printing documents or drafting e-mails of them)
Reading a document into a form (/ai/readings) is personal; the service lets only those read for a
form who may save it (services/ai_reading).
Everybody who works in the office may also keep tasks, documents, files, photos,
messages, calendar entries and notifications. Endpoints add finer checks of their own
(for example who may create which users).

Paths are relative to /api/v1 and match as a prefix, or as a regular expression when
they start with "^".
"""

from __future__ import annotations

import re

# one's own notifications (mark read, dismiss) – not the templates, not generating new ones
PERSONAL = ("/workspace", "/assistant", "/ai/readings", "/auth/users/me/preferences", "/auth/users/me/settings", "/auth/2fa", "/auth/logout", "/auth/refresh", "/auth/login",
            r"^/notifications/(all/receipt|[^/]+/receipt)$")
# requests that only read although they are POSTs: printing documents and e-mail drafts of them
READS = (r"^/documents/print$", r"^/documents/[^/]+/email-draft$")
OFFICE = ("/work-center", "/tasks", "/documents", "/files", "/photos", "/messages", "/calendar", "/dev-notes")
# Project file of a maintenance case: awarding and cancelling orders and deciding change orders
# commits money; the invoices of an order are bookkeeping. Both are not the technician's.
MAINTENANCE_DECISIONS = (r"^/maintenance/[^/]+/quotes/[^/]+/(accept|reject)$",
                         r"^/maintenance/[^/]+/orders/[^/]+/(cancel|complete)$",
                         r"^/maintenance/[^/]+/change-orders/[^/]+/(approve|reject)$")
MAINTENANCE_INVOICES = (r"^/maintenance/[^/]+/orders/[^/]+/invoices$", r"^/maintenance/[^/]+/invoice-links/[^/]+$")
# the factual check of an invoice: whether the work was ordered and done
INVOICE_FACTUAL = (r"^/invoices/[^/]+/review/factual-check$",)
BOOKKEEPING = ("/bank-imports", "/aktenwerk", "/invoice-review/receipts", "/bookings", "/accounts", "/categories", "/invoices", "/receivables", "/rent-charges", "/deposits",
               "/budgets", "/tax-rates", "/reports", "/billing/cost-items", "/billing/meter-documents", "/escalation/run", "/notifications/generate",
               r"^/contracts/[^/]+/dunning-campaign$", "/dunning", *MAINTENANCE_INVOICES,
               r"^/service-contracts/[^/]+/(invoices|payments|cost-transfers)(/[^/]+)?$")
# a metering document: readings for the technician, costs for bookkeeping (checked by the endpoint)
TECHNICAL = ("/maintenance", "/meters", "/billing/meter-documents", "/handover-protocols", *INVOICE_FACTUAL)
# inside an area the role may write, these paths stay closed to it
DENIED: dict[str, tuple[str, ...]] = {"techniker": MAINTENANCE_DECISIONS + MAINTENANCE_INVOICES,
                                      "buchhaltung": INVOICE_FACTUAL}
# /updates/configure decides where updates come from, so it is the owner's like installing them
OWNER_ONLY = ("/admin/restore", "/admin/import", "/data/import", "/admin/bulk-delete", "/updates/apply",
              "/updates/restart", "/updates/configure", "/admin/operations/second-target", "/admin/operations/plugins")

WRITE_AREAS: dict[str, tuple[str, ...] | None] = {
    "eigentuemer": None,          # None: everything
    "verwalter": None,
    "buchhaltung": PERSONAL + OFFICE + BOOKKEEPING,
    "techniker": PERSONAL + OFFICE + TECHNICAL,
    "readonly": PERSONAL + READS,
}

ROLE_LABELS = {"eigentuemer": "Eigentümer", "verwalter": "Verwalter", "buchhaltung": "Buchhaltung",
               "techniker": "Technik", "readonly": "Nur Lesen"}


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern.startswith("^"):
            if re.match(pattern, path):
                return True
        elif path == pattern or path.startswith(pattern.rstrip("/") + "/") or path.startswith(pattern + "?"):
            return True
    return False


def may_write(role: str | None, path: str) -> bool:
    """Whether `role` may send POST/PUT/PATCH/DELETE to `path` (relative to /api/v1)."""
    if role not in WRITE_AREAS:
        return False
    if role != "eigentuemer" and _matches(path, OWNER_ONLY):
        return False
    if _matches(path, DENIED.get(role, ())):
        return False
    areas = WRITE_AREAS[role]
    return areas is None or _matches(path, areas)


def write_areas(role: str | None) -> list[str] | None:
    """For the UI: None means everything, otherwise the paths the role may change."""
    if role not in WRITE_AREAS:
        return []
    areas = WRITE_AREAS[role]
    return None if areas is None else list(areas)
