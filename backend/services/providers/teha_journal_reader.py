"""Journal every TEHA read through the existing encrypted history core.

One provider operation equals one integration-history run. The wrapper performs
no retries and owns no credentials at rest. Complete private exchanges are
stored only as encrypted history artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from typing import Any, Callable, Generic, TypeVar

from ..integrations.history_store import SQLIntegrationHistoryStore
from ..integrations.history_types import HistoryActor, HistoryError
from .schema_observation import JsonSchemaObserver, json_snapshot
from .teha_transport import TehaTransport
from .teha_types import TehaDocumentContent, TehaError

T = TypeVar("T")
INTEGRATION_ID = "teha"


class TehaReceiveError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class TehaReadReceipt(Generic[T]):
    run_id: str
    operation: str
    value: T = field(repr=False)

    def __repr__(self) -> str:
        return (
            f"<TehaReadReceipt operation={self.operation!r} "
            f"run_id={self.run_id!r} private_value>"
        )


def _schema(value: Any) -> dict[str, Any]:
    return JsonSchemaObserver().observe(value).report()


def _request(
    operation: str,
    arguments: dict[str, Any],
    connection_key: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation": operation,
        "arguments": json_snapshot(arguments),
    }
    if connection_key is not None:
        payload["connection_key"] = connection_key
    return {
        "payload": payload,
        "privacy_policy": {
            "source": "teha_private_exchange",
            "credentials_in_request_artifact": False,
            "automatic_retry": False,
        },
    }


def _result_manifest(value: Any) -> dict[str, Any]:
    if isinstance(value, TehaDocumentContent):
        return {
            "type": "TehaDocumentContent",
            "reference": value.reference,
            "lieg_nr": value.lieg_nr,
            "sha256": value.sha256,
            "size_bytes": value.size_bytes,
            "media_type": value.media_type,
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "count": len(value),
            "item_type": type(value[0]).__name__ if value else None,
        }
    if is_dataclass(value):
        result = {"type": type(value).__name__}
        for key in ("account_id", "mandant_id"):
            if hasattr(value, key):
                result[key] = getattr(value, key)
        return result
    return {"type": type(value).__name__}


def history_exchange(
    detail: dict[str, Any],
    *,
    expected_operation: str | None = None,
    expected_connection_key: str | None = None,
) -> dict[str, Any]:
    """Extract the already-verified encrypted terminal exchange from detail."""
    if not isinstance(detail, dict) or detail.get("integration_id") != INTEGRATION_ID:
        raise TehaReceiveError("history_not_teha")
    payload = detail.get("payload")
    if expected_connection_key is not None:
        if (
            not isinstance(payload, dict)
            or payload.get("connection_key") != expected_connection_key
        ):
            raise TehaReceiveError("history_connection_mismatch")
    observations = detail.get("observations")
    if not isinstance(observations, list) or not observations:
        raise TehaReceiveError("history_evidence_invalid")
    terminal = observations[-1]
    if not isinstance(terminal, dict) or terminal.get("state") != "completed":
        raise TehaReceiveError("history_read_not_complete")
    artifacts = terminal.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TehaReceiveError("history_evidence_invalid")
    response = artifacts.get("response")
    if not isinstance(response, dict) or response.get("success") is not True:
        raise TehaReceiveError("history_read_not_complete")
    details = response.get("details")
    if not isinstance(details, dict):
        raise TehaReceiveError("history_evidence_invalid")
    operation = details.get("operation")
    if not isinstance(operation, str):
        raise TehaReceiveError("history_evidence_invalid")
    if expected_operation is not None and operation != expected_operation:
        raise TehaReceiveError("history_operation_mismatch")
    exchange = details.get("exchange")
    if not isinstance(exchange, dict):
        raise TehaReceiveError("history_exchange_missing")
    return json_snapshot(exchange)


class JournaledTehaReader:
    """Caller-owned authenticated portal session plus durable read evidence."""

    def __init__(
        self,
        transport: TehaTransport,
        history: SQLIntegrationHistoryStore,
        actor: HistoryActor,
        connection_key: str,
    ):
        if not isinstance(transport, TehaTransport):
            raise TypeError("transport must be TehaTransport")
        if not isinstance(history, SQLIntegrationHistoryStore):
            raise TypeError("history must be SQLIntegrationHistoryStore")
        if not isinstance(actor, HistoryActor):
            raise TypeError("actor must be HistoryActor")
        if (
            not isinstance(connection_key, str)
            or not connection_key
            or len(connection_key) > 200
            or connection_key != connection_key.strip()
            or any(ord(char) < 32 for char in connection_key)
        ):
            raise ValueError("connection_key must be an opaque stable connection namespace")
        self.transport = transport
        self.history = history
        self.actor = actor
        self.connection_key = connection_key
        self._usable = True

    def _poison(self) -> None:
        self._usable = False
        self.transport.close()

    def _terminal_response(
        self,
        operation: str,
        *,
        success: bool,
        message: str,
        result: Any = None,
        error: TehaError | None = None,
    ) -> dict[str, Any]:
        exchange = self.transport.private_last_exchange_snapshot()
        exchange_schema = self.transport.private_exchange_schema_snapshot()
        if (
            operation == "read_document"
            and success
            and isinstance(result, TehaDocumentContent)
            and isinstance(exchange, dict)
        ):
            # Preserve the complete unknown envelope/metadata, but do not
            # duplicate a potentially large PDF as base64 inside JSON history.
            # The actual bytes belong in the existing immutable original core.
            response = exchange.get("response")
            body = response.get("body") if isinstance(response, dict) else None
            if isinstance(body, dict) and "content" in body:
                body["content"] = {
                    "omitted": "document_bytes",
                    "sha256": result.sha256,
                    "size_bytes": result.size_bytes,
                    "media_type": result.media_type,
                }
        details: dict[str, Any] = {
            "operation": operation,
            "automatic_retry": False,
            "exchange": exchange,
            "exchange_schema": exchange_schema,
        }
        if success:
            details["result_manifest"] = _result_manifest(result)
        elif error is not None:
            details["error"] = {
                "code": error.code,
                "retryable": error.retryable,
                "retry_after_seconds": error.retry_after_seconds,
                "http_status": error.http_status,
            }
        return {
            "success": success,
            "message": message,
            "details": details,
        }

    def _run(
        self,
        operation: str,
        arguments: dict[str, Any],
        call: Callable[[], T],
    ) -> TehaReadReceipt[T]:
        if not self._usable:
            raise TehaReceiveError("reader_session_not_usable")
        accepted = _request(operation, arguments, self.connection_key)
        ticket = self.history.accept(
            INTEGRATION_ID,
            self.actor,
            accepted,
            _schema(accepted),
        )
        self.history.append(
            ticket,
            "execution_started",
            actor=self.actor,
        )
        try:
            value = call()
        except TehaError as error:
            exchange = self.transport.private_last_exchange_snapshot()
            state = (
                "observation_failed"
                if error.code == "provider_observation_failed"
                else "rejected"
                if exchange is not None
                or error.code
                in {
                    "invalid_credentials_input",
                    "provider_operation_not_allowed",
                    "authentication_required",
                    "provider_schema_changed",
                    "provider_document_invalid_base64",
                    "provider_document_not_pdf",
                    "document_budget_exceeded",
                    "response_budget_exceeded",
                }
                else "outcome_uncertain"
            )
            response = self._terminal_response(
                operation,
                success=False,
                message=f"TEHA read failed safely: {error.code}",
                error=error,
            )
            try:
                self.history.append(
                    ticket,
                    state,
                    {"response": response, "schema": _schema(response)},
                    actor=self.actor,
                )
            except HistoryError:
                self._poison()
                raise
            raise
        except BaseException:
            # Unknown exceptions can contain private provider/library values and
            # do not prove whether a read reached the remote endpoint.
            response = {
                "success": False,
                "message": "TEHA read outcome is unconfirmed.",
                "details": {
                    "operation": operation,
                    "automatic_retry": False,
                    "error": {"code": "unexpected_read_failure"},
                },
            }
            try:
                self.history.append(
                    ticket,
                    "outcome_uncertain",
                    {"response": response, "schema": _schema(response)},
                    actor=self.actor,
                )
            except HistoryError:
                self._poison()
            raise
        response = self._terminal_response(
            operation,
            success=True,
            message="TEHA read completed and fully journaled.",
            result=value,
        )
        try:
            self.history.append(
                ticket,
                "completed",
                {"response": response, "schema": _schema(response)},
                actor=self.actor,
            )
        except HistoryError:
            # Never hand a caller a successful read without its durable
            # encrypted exchange evidence.
            self._poison()
            raise
        return TehaReadReceipt(ticket.run_id, operation, value)

    def authenticate(self, username: str, password: str):
        # Credentials deliberately never enter accepted history artifacts.
        return self._run(
            "authenticate",
            {"credentials": "omitted"},
            lambda: self.transport.authenticate(username, password),
        )

    def list_property_periods(self):
        return self._run(
            "list_property_periods",
            {},
            self.transport.list_property_periods,
        )

    def list_documents(self, lieg_nr: str):
        return self._run(
            "list_documents",
            {"lieg_nr": lieg_nr},
            lambda: self.transport.list_documents(lieg_nr),
        )

    def read_document(self, lieg_nr: str, reference: str):
        return self._run(
            "read_document",
            {"lieg_nr": lieg_nr, "reference": reference},
            lambda: self.transport.read_document(lieg_nr, reference),
        )

    def list_technical_orders(self):
        return self._run(
            "list_technical_orders",
            {},
            self.transport.list_technical_orders,
        )

    def read_order_users(self, termin_id: int):
        return self._run(
            "read_order_users",
            {"termin_id": termin_id},
            lambda: self.transport.read_order_users(termin_id),
        )
