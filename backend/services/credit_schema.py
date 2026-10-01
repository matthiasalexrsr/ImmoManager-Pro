"""Detect an old local allocation check before a negative bank payout."""
from sqlalchemy import inspect


def require_negative_allocation_schema(connection):
    checks = inspect(connection).get_check_constraints("bookings")
    if any(check.get("name") == "ck_bookings_allocation"
           and "abs(" in check.get("sqltext", "").lower().replace(" ", "") for check in checks):
        return
    from .payments import FinancialConsistencyError
    raise FinancialConsistencyError("Die lokale Bankbuchungsstruktur benötigt das Guthaben-Upgrade. Anwendung stoppen, Vollsicherung erstellen und das dokumentierte Offline-Schema-Upgrade ausführen. Der Auszahlungsentwurf bleibt erhalten.")
