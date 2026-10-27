"""Read-only HTTP transport for the actually observed TEHA customer portal.

No durable credentials, refresh guesses, arbitrary URLs or business writes.
The two document POSTs and authentication are observed portal operations.
Caller-owned jobs must handle safe errors, retries, scopes and publication.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import inspect
import json
import math
import re
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any

import httpx

from .exchange_observation import PrivateJsonExchange, observe_json_exchange
from .schema_observation import json_snapshot
from .teha_types import (
    TehaAccount,
    TehaDocument,
    TehaDocumentContent,
    TehaError,
    TehaOrderUser,
    TehaPropertyPeriod,
    TehaTechnicalOrder,
)

TEHA_ORIGIN = "https://kunden.socs.ws"


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TehaError("provider_schema_changed")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise TehaError("provider_schema_changed")
    return value


def _number(value: Any, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        raise TehaError("provider_schema_changed")
    return value


def _check_status(payload: dict[str, Any], *, required: bool = False) -> None:
    if required or "success" in payload:
        if type(payload.get("success")) is not bool:
            raise TehaError("provider_schema_changed")
        if not payload["success"]:
            # Never echo fehlermeldung: it can contain account or property data.
            raise TehaError("provider_operation_failed")


def _rows(payload: dict[str, Any], key: str, *, success: bool = True) -> list[dict[str, Any]]:
    _check_status(payload, required=success)
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise TehaError("provider_schema_changed")
    return [_object(row) for row in rows]


def _positive(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    except ValueError:
        pass
    try:
        at = parsedate_to_datetime(value)
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return max(0.0, (at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _json_value(raw: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def finite(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError
        return result

    def reject(_value):
        raise ValueError

    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                          parse_float=finite, parse_constant=reject)
    except (ValueError, UnicodeError, RecursionError):
        raise TehaError("provider_response_invalid_json") from None


class TehaTransport:
    """One caller-owned portal session; not shared concurrently across users.

    Budgets bound each response/document, never the total number of records.
    A custom httpx transport is a test seam; the production default verifies
    TLS and ignores ambient proxy/netrc credentials. No redirect is followed.
    """

    def __init__(self, *, max_response_bytes: int = 64 * 1024**2,
                 max_document_bytes: int = 48 * 1024**2, timeout_seconds: float = 30.0,
                 response_deadline_seconds: float = 120.0,
                 private_exchange_sink: Callable[[PrivateJsonExchange], None] | None = None,
                 transport: httpx.BaseTransport | None = None):
        if (type(max_response_bytes) is not int or max_response_bytes <= 0
                or type(max_document_bytes) is not int or max_document_bytes <= 0
                or not _positive(timeout_seconds) or not _positive(response_deadline_seconds)):
            raise TehaError("invalid_transport_budget")
        if private_exchange_sink is not None and (not callable(private_exchange_sink)
                                                 or inspect.iscoroutinefunction(private_exchange_sink)):
            raise TehaError("invalid_observation_sink")
        self._response_budget = max_response_bytes
        self._document_budget = max_document_bytes
        self._response_deadline = response_deadline_seconds
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._private_exchange_sink = private_exchange_sink
        self._last_exchange: PrivateJsonExchange | None = None
        self._closed = False
        self._client = httpx.Client(base_url=TEHA_ORIGIN, verify=True, trust_env=False,
                                    follow_redirects=False, timeout=timeout_seconds,
                                    limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
                                    headers={"Accept": "application/json", "Accept-Encoding": "identity"}, transport=transport)

    def __repr__(self) -> str:
        return f"<TehaTransport authenticated={self.authenticated!r} closed={self._closed!r}>"

    @property
    def authenticated(self) -> bool:
        return bool(self._access_token) and not self._closed

    def _clear_auth(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._client.cookies.clear()

    def private_last_exchange_snapshot(self) -> dict[str, Any] | None:
        """Only the latest parsed response, explicit private access, no history."""
        return self._last_exchange.private_snapshot() if self._last_exchange else None

    def private_exchange_schema_snapshot(self) -> dict[str, Any] | None:
        """Complete latest request/response shape; no lifetime accumulation."""
        return self._last_exchange.private_schema_snapshot() if self._last_exchange else None

    def _session_secret_values(self) -> tuple[str, ...]:
        return (self._access_token or "", self._refresh_token or "",
                *(cookie.value or "" for cookie in self._client.cookies.jar))

    def _observe_exchange(self, response: httpx.Response, body: dict | None, payload: Any,
                          known_secret_values: tuple[str, ...]) -> None:
        try:
            request = response.request
            exchange = observe_json_exchange(method=request.method, path=request.url.path,
                query=[[key, value] for key, value in request.url.params.multi_items()], body=body,
                request_headers=request.headers.multi_items(), status=response.status_code,
                response_headers=response.headers.multi_items(), payload=payload,
                known_secret_values=(*known_secret_values, *self._session_secret_values(),
                                     *(cookie.value or "" for cookie in response.cookies.jar)))
            if self._private_exchange_sink is not None:
                result: Any = self._private_exchange_sink(exchange.independent_copy())
                if result is not None:
                    if inspect.iscoroutine(result):
                        result.close()
                    raise ValueError("invalid_observation_sink_result")
            self._last_exchange = exchange
        except Exception:
            # Neither caller callback exceptions nor schema/copy failures may
            # masquerade as success or expose private request/response text.
            raise TehaError("provider_observation_failed") from None

    def close(self) -> None:
        self._clear_auth()
        self._last_exchange = None
        self._private_exchange_sink = None
        self._closed = True
        self._client.close()

    def __enter__(self) -> TehaTransport:
        if self._closed:
            raise TehaError("transport_closed")
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def _request(self, method: str, path: str, *, body: dict | None = None,
                 login: bool = False) -> dict[str, Any]:
        if self._closed:
            raise TehaError("transport_closed")
        allowed = (method, path) in {
            ("POST", "/api/user"), ("GET", "/api/liegenschaften"),
            ("POST", "/api/Liegenschaften/documents"), ("POST", "/api/Liegenschaften/document-content"),
            ("GET", "/api/auftrag"),
        } or (method == "GET" and re.fullmatch(r"/api/Auftrag/[1-9][0-9]*", path) is not None)
        if not allowed or login != (path == "/api/user"):
            raise TehaError("provider_operation_not_allowed")
        if not login and not self._access_token:
            raise TehaError("authentication_required")
        self._last_exchange = None
        known_secrets = (*self._session_secret_values(),
                         body.get("PasswordHash", "") if login and body else "")
        headers = {} if login else {"Authorization": "Bearer " + str(self._access_token)}
        started = monotonic()
        try:
            with self._client.stream(method, path, json=body, headers=headers) as response:
                status = response.status_code
                if 300 <= status < 400:
                    status_error = TehaError("provider_redirect_denied", http_status=status)
                else:
                    status_error = None
                if status == 401:
                    self._clear_auth()
                    status_error = TehaError("authentication_failed" if login else "authentication_expired",
                                             http_status=status)
                if status == 403:
                    status_error = TehaError("provider_permission_denied", http_status=status)
                if status == 429:
                    status_error = TehaError("provider_rate_limited", retryable=True,
                        retry_after_seconds=_retry_after(response.headers.get("Retry-After")), http_status=status)
                if status in {408, 425} or 500 <= status < 600:
                    status_error = TehaError("provider_temporarily_unavailable", retryable=True,
                        retry_after_seconds=_retry_after(response.headers.get("Retry-After")), http_status=status)
                if not 200 <= status < 300 and status_error is None:
                    status_error = TehaError("authentication_failed" if login else "provider_http_error",
                                             http_status=status)
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if mime != "application/json" and not (mime.startswith("application/") and mime.endswith("+json")):
                    if status_error is not None:
                        raise status_error
                    raise TehaError("provider_response_not_json")
                length = response.headers.get("Content-Length")
                if length and length.isascii() and length.isdigit():
                    try:
                        if int(length) > self._response_budget:
                            raise TehaError("response_budget_exceeded")
                    except ValueError:
                        raise TehaError("provider_schema_changed") from None
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    if monotonic() - started > self._response_deadline:
                        raise TehaError("provider_response_deadline", retryable=True)
                    size += len(chunk)
                    if size > self._response_budget:
                        raise TehaError("response_budget_exceeded")
                    chunks.append(chunk)
                if monotonic() - started > self._response_deadline:
                    raise TehaError("provider_response_deadline", retryable=True)
                try:
                    payload = _json_value(b"".join(chunks))
                except TehaError:
                    # A broken error body remains an HTTP failure, never an
                    # accepted complete JSON observation. 2xx stays strict.
                    if status_error is not None:
                        raise status_error from None
                    raise
                self._observe_exchange(response, body, payload, known_secrets)
                if status_error is not None:
                    raise status_error
                # Authentication alone needs ephemeral raw tokens. Every other
                # DTO is projected from the whole sanitized envelope, so a
                # secret named at top level cannot leak through a row alias.
                if login:
                    return _object(payload)
                if self._last_exchange is None:
                    raise TehaError("provider_observation_failed")
                return _object(self._last_exchange.private_response_snapshot())
        except httpx.TimeoutException:
            raise TehaError("provider_timeout", retryable=True) from None
        except httpx.RequestError:
            raise TehaError("provider_network_error", retryable=True) from None

    def authenticate(self, username: str, password: str) -> TehaAccount:
        # A failed replacement login must not silently retain an old identity.
        self._clear_auth()
        self._last_exchange = None
        if (not isinstance(username, str) or not username.strip() or not isinstance(password, str)
                or not password or any(c in username for c in "\r\n\0")):
            raise TehaError("invalid_credentials_input")
        try:
            return self._authenticate(username, password)
        except BaseException:
            self._clear_auth()
            raise

    def _authenticate(self, username: str, password: str) -> TehaAccount:
        payload = self._request("POST", "/api/user", login=True,
                                body={"Mandant": 1, "Username": username, "PasswordHash": password})
        if "error" not in payload:
            raise TehaError("provider_schema_changed")
        if payload.get("error") is not None:
            raise TehaError("authentication_failed")
        access = _text(payload.get("accessToken"))
        if not access.isascii() or any(c.isspace() for c in access):
            raise TehaError("provider_schema_changed")
        refresh = payload.get("refreshToken")
        if refresh is not None:
            refresh = _text(refresh)
        identifier = _number(payload.get("id"))
        mandant = _number(payload.get("mandantId"))
        if mandant != 1:
            raise TehaError("provider_account_mismatch")
        if self._last_exchange is None:
            raise TehaError("provider_observation_failed")
        # The profile and its shape share all request/response/header secret
        # knowledge. A neutral alias of a secret header cannot bypass via DTO.
        profile_schema = self._last_exchange.private_response_schema_snapshot()
        private_source = _object(self._last_exchange.private_response_snapshot())
        self._access_token = access
        self._refresh_token = refresh
        return TehaAccount(account_id=identifier, mandant_id=mandant, _source=private_source,
                           _profile_schema=profile_schema)

    def list_property_periods(self) -> list[TehaPropertyPeriod]:
        result = []
        for row in _rows(self._request("GET", "/api/liegenschaften"), "liegenschaften"):
            identity = _object(row.get("liegId"))
            result.append(TehaPropertyPeriod(object_id=_number(identity.get("id")),
                period_number=_number(identity.get("abrechnungLaufendeNr"), zero=True),
                lieg_nr=_text(row.get("liegenschaftenNummer")),
                period_from_raw=_text(row.get("abrechnungVon")), period_to_raw=_text(row.get("abrechnungBis")),
                _source=json_snapshot(row)))
        return result

    def list_documents(self, lieg_nr: str) -> list[TehaDocument]:
        lieg_nr = _text(lieg_nr)
        result = []
        for row in _rows(self._request("POST", "/api/Liegenschaften/documents", body={"LiegNr": lieg_nr}),
                         "documents", success=False):
            _object(row.get("properties"))
            if not isinstance(row.get("attachments"), list):
                raise TehaError("provider_schema_changed")
            result.append(TehaDocument(reference=_text(row.get("reference")), filename=_text(row.get("fileName")),
                                       lieg_nr=lieg_nr, _source=json_snapshot(row)))
        return result

    def read_document(self, lieg_nr: str, reference: str) -> TehaDocumentContent:
        lieg_nr, reference = _text(lieg_nr), _text(reference)
        payload = self._request("POST", "/api/Liegenschaften/document-content",
                                body={"Ref": reference, "LiegNr": lieg_nr})
        _check_status(payload)
        encoded = _text(payload.get("content"))
        if len(encoded) > 4 * ((self._document_budget + 2) // 3):
            raise TehaError("document_budget_exceeded")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeError, binascii.Error):
            raise TehaError("provider_document_invalid_base64") from None
        if base64.b64encode(content).decode("ascii") != encoded:
            raise TehaError("provider_document_invalid_base64")
        if len(content) > self._document_budget:
            raise TehaError("document_budget_exceeded")
        if not content.startswith(b"%PDF-"):
            raise TehaError("provider_document_not_pdf")
        return TehaDocumentContent(reference=reference, lieg_nr=lieg_nr, content=content,
                                   sha256=hashlib.sha256(content).hexdigest())

    def list_technical_orders(self) -> list[TehaTechnicalOrder]:
        result = []
        for row in _rows(self._request("GET", "/api/auftrag"), "auftraege"):
            result.append(TehaTechnicalOrder(termin_id=_number(row.get("terminId")),
                order_number=_number(row.get("auftragNummer")), period_number=_number(row.get("abrLfdNr"), zero=True),
                lieg_nr=_text(row.get("liegenschaftsnummer")), termin_from_raw=_text(row.get("terminVon")),
                termin_to_raw=_text(row.get("terminBis")), period_to_raw=_text(row.get("abrechnungBis")),
                _source=json_snapshot(row)))
        return result

    def read_order_users(self, termin_id: int) -> list[TehaOrderUser]:
        termin_id = _number(termin_id)
        result = []
        for row in _rows(self._request("GET", f"/api/Auftrag/{termin_id}"), "nutzerInAuftrag"):
            result.append(TehaOrderUser(user_id=_number(row.get("id")), unit_id=_number(row.get("neId")),
                                        sequence_number=_text(row.get("lfdNr")), _source=json_snapshot(row)))
        return result
