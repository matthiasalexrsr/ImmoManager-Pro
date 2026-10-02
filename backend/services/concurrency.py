"""Conditional edits for versioned domain records.

The strong ETag binds the resource collection, ID and exact UTC microsecond
``updated_at``. Clients without If-Match retain legacy compatibility; this is
not a universal locking policy. Financial POST commands keep their own guards.
Register ConcurrencyMiddleware on the application to propagate request-local
conditions into sync endpoint workers and emit single-record ETags.
"""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator
from urllib.parse import quote, unquote

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# URI collection -> domain collection/table. Only direct resource CRUD is
# conditional; archive/payment/import/billing commands are separate workflows.
COLLECTIONS = {
    "portfolios": "portfolios", "properties": "properties", "units": "units",
    "accounts": "accounts", "categories": "categories", "tenants": "tenants",
    "contracts": "contracts", "bookings": "bookings", "receivables": "receivables",
    "invoices": "invoices", "maintenance": "maintenance_cases", "documents": "documents",
    "tasks": "tasks", "calendar": "calendar_events", "listings": "listings",
    "leads": "leads", "viewings": "viewing_appointments", "deposits": "deposits",
    "tax-rates": "tax_rates", "budgets": "budgets", "rent-adjustments": "rent_adjustments",
    "handover-protocols": "handover_protocols", "handover-protocols/meter-readings": "meter_readings",
    "insurances": "insurances", "contacts": "contacts", "meters": "meters",
    "meters/readings": "standalone_meter_readings", "rent-charges": "rent_charges",
    "notifications": "notifications", "notifications/templates": "notification_templates",
    "messages/threads": "message_threads", "escalation/rules": "escalation_rules",
    "billing/periods": "billing_periods", "billing/allocation-keys": "allocation_keys",
    "billing/cost-items": "cost_items", "billing/statements": "utility_statements",
}


def utc_datetime(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def next_updated_at(previous: datetime | None, candidate: datetime | None = None) -> datetime:
    now = utc_datetime(candidate or datetime.now(timezone.utc))
    return max(now, utc_datetime(previous) + timedelta(microseconds=1)) if previous else now


def etag(collection: str, entity_id: str, updated_at: datetime | str) -> str:
    stamp = utc_datetime(updated_at).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return f'"immo-v1:{quote(collection, safe="")}:{quote(entity_id, safe="")}:{stamp}"'


@dataclass(frozen=True)
class EditRevision:
    collection: str
    entity_id: str
    updated_at: datetime

    @property
    def table(self) -> str:
        return COLLECTIONS[self.collection]


_revision: ContextVar[EditRevision | None] = ContextVar("immo_edit_revision", default=None)
memory_mutation_depth: ContextVar[int] = ContextVar("immo_memory_mutation_depth", default=0)


@contextmanager
def revision_scope(revision: EditRevision | None) -> Iterator[None]:
    token = _revision.set(revision)
    try:
        yield
    finally:
        _revision.reset(token)


def conflict() -> HTTPException:
    return HTTPException(status_code=412, detail="Der Datensatz wurde zwischenzeitlich geändert oder entfernt. Ihr Entwurf wurde nicht gespeichert. Bitte prüfen Sie den aktuellen Stand.")


def expected_revision(table: str, entity_id: str) -> EditRevision | None:
    expected = _revision.get()
    if expected and (expected.table != table or expected.entity_id != entity_id):
        raise conflict()
    return expected


def guard_memory_revision(table: str, entity_id: str, current) -> None:
    expected = expected_revision(table, entity_id)
    if not expected:
        return
    stamp = getattr(current, "updated_at", None)
    if stamp is None or utc_datetime(stamp) != expected.updated_at:
        raise conflict()


def parse_revision(value: str) -> EditRevision:
    try:
        if not value.startswith('"immo-v1:') or not value.endswith('"') or "," in value:
            raise ValueError("A single strong ImmoManager ETag is required")
        collection, entity_id, stamp = value[len('"immo-v1:'):-1].split(":", 2)
        collection, entity_id = unquote(collection), unquote(entity_id)
        if collection not in COLLECTIONS or not entity_id or not stamp:
            raise ValueError("Unknown resource")
        return EditRevision(collection, entity_id, utc_datetime(stamp))
    except (TypeError, ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail="If-Match benötigt genau einen gültigen starken Bearbeitungsstand dieses Datensatzes.") from error


def resource_path(path: str) -> tuple[str, str | None] | None:
    if not path.startswith("/api/v1/"):
        return None
    suffix = path[len("/api/v1/"):].rstrip("/")
    parts = suffix.split("/")
    if len(parts) in {3, 4} and parts[0] == "handover-protocols" and parts[2] == "meter-readings":
        return "handover-protocols/meter-readings", unquote(parts[3]) if len(parts) == 4 else None
    if len(parts) == 3 and parts[:2] == ["meters", "readings"] and parts[2] == "all":
        return "meters/readings", None
    if len(parts) == 3 and parts[0] == "meters" and parts[2] == "readings":
        return "meters/readings", None
    for collection in sorted(COLLECTIONS, key=len, reverse=True):
        if suffix == collection:
            return collection, None
        prefix = collection + "/"
        if suffix.startswith(prefix) and "/" not in suffix[len(prefix):]:
            return collection, unquote(suffix[len(prefix):])
    return None


class ConcurrencyMiddleware:
    """Pure ASGI context propagation, without a check-before-write race.

    Conditions are enforced by the repositories inside their actual mutation.
    Response buffering is limited to direct single-record JSON CRUD responses;
    streaming files/reports and financial commands pass through unchanged.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        resource = resource_path(scope.get("path", ""))
        method = scope.get("method", "GET")
        headers = [value.decode("latin-1") for name, value in scope.get("headers", []) if name.lower() == b"if-match"]
        expected = None
        try:
            if headers and method in {"PUT", "PATCH", "DELETE"}:
                if len(headers) != 1:
                    raise HTTPException(status_code=400, detail="If-Match darf nur einmal angegeben werden.")
                if not resource or not resource[1]:
                    raise HTTPException(status_code=400, detail="Dieser Endpunkt unterstützt keine bedingte Stammdatenbearbeitung.")
                expected = parse_revision(headers[0])
                if (expected.collection, expected.entity_id) != resource:
                    raise conflict()
        except HTTPException as error:
            response = JSONResponse(status_code=error.status_code, content={"error": {"code": "EDIT_CONFLICT" if error.status_code == 412 else "VALIDATION_ERROR", "message": error.detail}})
            await response(scope, receive, send)
            return

        start: Message | None = None
        body = bytearray()
        buffer_response = bool(resource and (method == "POST" or resource[1] and method in {"GET", "PUT", "PATCH"}))

        async def send_version(message: Message) -> None:
            nonlocal start, buffer_response
            if message["type"] == "http.response.start":
                response_headers = message.get("headers", [])
                content_type = next((value for key, value in response_headers if key.lower() == b"content-type"), b"")
                buffer_response = buffer_response and 200 <= message["status"] < 300 and b"application/json" in content_type
                if buffer_response:
                    start = message
                    return
            elif message["type"] == "http.response.body" and buffer_response:
                body.extend(message.get("body", b""))
                if message.get("more_body", False):
                    return
                assert start is not None and resource is not None
                try:
                    data = json.loads(body)
                    if isinstance(data, dict) and isinstance(data.get("id"), str) and isinstance(data.get("updated_at"), str):
                        version = etag(resource[0], data["id"], data["updated_at"])
                        start = {**start, "headers": [*start.get("headers", []), (b"etag", version.encode("ascii"))]}
                except (ValueError, TypeError, UnicodeError):
                    pass
                await send(start)
                await send({"type": "http.response.body", "body": bytes(body)})
                return
            await send(message)

        with revision_scope(expected):
            await self.app(scope, receive, send_version)
