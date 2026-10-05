"""Who may change what: write access by role and area of the API.

Reading is open to every signed-in user. For writing:
- eigentuemer   everything
- verwalter     everything except restoring, importing and bulk deleting data
- buchhaltung   money: bookings, accounts, invoices, receivables, deposits, budgets,
                costs of the utility statement, dunning
- techniker     building: maintenance, meters, handover protocols
- readonly      only personal settings
Everybody who works in the office may also keep tasks, documents, files, photos,
messages, calendar entries and notifications. Endpoints add finer checks of their own
(for example who may create which users).

Paths are relative to /api/v1 and match as a prefix, or as a regular expression when
they start with "^".
"""

from __future__ import annotations

import re

PERSONAL = ("/auth/users/me/preferences", "/auth/2fa", "/auth/logout", "/auth/refresh", "/auth/login",
            "/notifications")
OFFICE = ("/tasks", "/documents", "/files", "/photos", "/messages", "/calendar", "/dev-notes")
BOOKKEEPING = ("/bookings", "/accounts", "/categories", "/invoices", "/receivables", "/rent-charges", "/deposits",
               "/budgets", "/tax-rates", "/reports", "/billing/cost-items", "/escalation/run",
               r"^/contracts/[^/]+/dunning-campaign$")
TECHNICAL = ("/maintenance", "/meters", "/handover-protocols")
OWNER_ONLY = ("/admin/restore", "/admin/import", "/data/import", "/admin/bulk-delete", "/updates/apply",
              "/updates/restart")

WRITE_AREAS: dict[str, tuple[str, ...] | None] = {
    "eigentuemer": None,          # None: everything
    "verwalter": None,
    "buchhaltung": PERSONAL + OFFICE + BOOKKEEPING,
    "techniker": PERSONAL + OFFICE + TECHNICAL,
    "readonly": PERSONAL,
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
    areas = WRITE_AREAS[role]
    return areas is None or _matches(path, areas)


def write_areas(role: str | None) -> list[str] | None:
    """For the UI: None means everything, otherwise the paths the role may change."""
    if role not in WRITE_AREAS:
        return []
    areas = WRITE_AREAS[role]
    return None if areas is None else list(areas)
