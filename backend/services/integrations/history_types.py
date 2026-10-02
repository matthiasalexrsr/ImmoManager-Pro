"""Safe journal errors, positive operational budgets and explicit principals."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any


class HistoryError(RuntimeError):
    def __init__(self, code: str, status: int = 503):
        self.code, self.status = code, status
        self.message = {
            "HISTORY_NOT_CONFIGURED": "Die dauerhafte Integrationshistorie ist nicht eingerichtet.",
            "HISTORY_KEY_UNAVAILABLE": "Die vollständigen stabilen Verschlüsselungsschlüssel wiederherstellen.",
            "HISTORY_CORRUPT": "Die Integrationshistorie ist beschädigt. Vollständige unveränderte Sicherung verwenden.",
            "HISTORY_BUDGET_EXCEEDED": "Das Vorgangsbudget reicht nicht aus. Budget erhöhen oder kleinere Seite wählen.",
            "HISTORY_BUSY": "Ein Lauf ist noch offen. Ergebnis prüfen und anschließend erneut versuchen.",
            "HISTORY_CURSOR_INVALID": "Die Historienseite ist nicht mehr gültig. Liste neu laden.",
            "HISTORY_NOT_FOUND": "Integrationslauf nicht gefunden.",
            "HISTORY_FORBIDDEN": "Installationsverwaltung mit aktuellen Benutzerrechten erforderlich.",
            "HISTORY_WRITE_FAILED": "Historie konnte nicht dauerhaft bestätigt werden. Einen gestarteten Lauf nicht blind wiederholen.",
            "HISTORY_INPUT_INVALID": "Nur endliche, gültige JSON-Werte für die Integrationshistorie verwenden.",
        }.get(code, "Die Integrationshistorie konnte nicht sicher verarbeitet werden.")
        super().__init__(code)


@dataclass(frozen=True)
class HistoryLimits:
    artifact_bytes: int = 16 * 1024 * 1024
    page_bytes: int = 32 * 1024 * 1024
    timeout_seconds: float = 60.0
    temp_bytes: int = 512 * 1024 * 1024

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.artifact_bytes, self.page_bytes, self.temp_bytes)):
            raise ValueError("History byte budgets must be positive integers")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("History time budget must be finite and positive")


@dataclass(frozen=True)
class HistoryActor:
    actor_id: str
    origin: str
    captured: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def authenticated(cls):
        from ..portfolio_scope import current_scope, refresh_scope

        scope = refresh_scope(current_scope())
        if scope is None or scope.role not in {"eigentuemer", "verwalter"} or not scope.unrestricted:
            raise HistoryError("HISTORY_FORBIDDEN", 403)
        return cls(scope.user_id, "authenticated_request", scope)

    @classmethod
    def internal(cls, service_id: str):
        """Explicit trusted Python caller; never constructed from HTTP JSON."""
        if not isinstance(service_id, str) or not service_id or any(ord(c) < 32 for c in service_id):
            raise ValueError("Internal history principal must be named")
        return cls(service_id, "internal_service")

    def refresh(self):
        if self.origin == "authenticated_request":
            from ..portfolio_scope import refresh_scope

            scope = refresh_scope(self.captured)
            if scope is None or scope.user_id != self.actor_id or scope.role not in {"eigentuemer", "verwalter"} or not scope.unrestricted:
                raise HistoryError("HISTORY_FORBIDDEN", 403)
        elif self.origin != "internal_service" or not self.actor_id:
            raise HistoryError("HISTORY_FORBIDDEN", 403)

    def fingerprint(self):
        scope = self.captured
        value = [self.actor_id, self.origin, None if scope is None else [scope.role, scope.unrestricted, scope.portfolio_ids]]
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, repr=False)
class RunTicket:
    run_id: str
    token: str
