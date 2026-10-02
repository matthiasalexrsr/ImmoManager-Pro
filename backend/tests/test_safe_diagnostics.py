"""Exercise actual errors: preserve recovery and useful locations without PII."""

import json
import logging
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from backend.error_helpers import DatabaseOperationError, safe_db_operation
from backend.exceptions import _request_context, register_exception_handlers
from backend.logging_config import JSONFormatter, TextFormatter
from backend.repositories.base import BaseRepository
from backend.safe_diagnostics import exception_diagnostic

PRIVATE = "tenant@example.invalid-DE02120300000000202051"


@pytest.mark.parametrize("formatter", [JSONFormatter(), TextFormatter()])
def test_real_sql_conflict_rolls_back_and_session_remains_usable(caplog, formatter):
    engine = create_engine("sqlite://")
    table = Table("synthetic_private_accounts", MetaData(),
                  Column("id", Integer, primary_key=True), Column("private_name", String, unique=True))
    table.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(table.insert().values(id=1, private_name=PRIVATE))
        session.commit()

        class Repository:
            db = session

            @safe_db_operation("create_account")
            def insert(self, identity, private_name):
                self.db.execute(table.insert().values(id=identity, private_name=private_name))
                self.db.commit()

        repository = Repository()
        with caplog.at_level(logging.INFO), pytest.raises(DatabaseOperationError) as raised:
            repository.insert(2, PRIVATE)
        repository.insert(3, "synthetic-second")
        assert session.scalar(select(table.c.id).where(table.c.id == 3)) == 3
        output = "\n".join(formatter.format(record) for record in caplog.records)
        assert PRIVATE not in output
        assert "INSERT INTO" not in output
        assert "IntegrityError" in output and "create_account" in output
        assert "test_safe_diagnostics.py" in output
        assert raised.value.__cause__ is not None
    engine.dispose()


@pytest.mark.parametrize("formatter", [JSONFormatter(), TextFormatter()])
@pytest.mark.parametrize("argument_style", ["tuple", "mapping", "message"])
def test_formatter_redacts_exception_message_arguments_and_traceback(formatter, argument_style):
    try:
        raise RuntimeError(PRIVATE)
    except RuntimeError as error:
        if argument_style == "tuple":
            msg, args = "Transport failed: %s", (error,)
        elif argument_style == "mapping":
            msg, args = "Transport failed: %(error)s", ({"error": error},)
        else:
            msg, args = error, ()
        record = logging.LogRecord("diagnostic", logging.ERROR, __file__, 81, msg, args, sys.exc_info())
        original_msg, original_args = record.msg, record.args
        output = formatter.format(record)
        assert PRIVATE not in output
        assert "RuntimeError" in output and "test_safe_diagnostics.py" in output
        assert str(__file__) not in output
        assert record.msg is original_msg and record.args is original_args
        if isinstance(formatter, JSONFormatter):
            assert json.loads(output)["exception_type"] == "RuntimeError"


def test_handler_logs_route_template_and_recovers_on_next_request(caplog):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/api/documents/{document_id}")
    def private_error(document_id: str):
        raise RuntimeError(PRIVATE + document_id)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.CRITICAL, logger="backend.exceptions"):
        response = client.get(f"/api/documents/{PRIVATE}?search={PRIVATE}&token=synthetic-secret")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    records = [record for record in caplog.records if record.name == "backend.exceptions"]
    assert len(records) == 1
    output = JSONFormatter().format(records[0])
    assert PRIVATE not in output and "synthetic-secret" not in output
    assert "/api/documents/{document_id}" in output and "RuntimeError" in output
    assert "query_count" in output
    assert client.get("/api/health").json() == {"ok": True}


def test_request_context_excludes_raw_path_query_username_and_ip():
    request = Request({"type": "http", "method": "GET", "path": "/api/" + PRIVATE,
                       "query_string": f"search={PRIVATE}&email={PRIVATE}".encode(),
                       "headers": [], "client": ("192.0.2.77", 1234)})
    request.state.user = SimpleNamespace(id="opaque-user-id", username=PRIVATE)
    context = _request_context(request)
    assert context["path"] == "[unmatched]" and context["query_count"] == 2
    assert context["user_id"] == "opaque-user-id"
    assert PRIVATE not in str(context) and "192.0.2.77" not in str(context)


def test_invalid_database_row_diagnostics_do_not_dump_pydantic_input(caplog, monkeypatch):
    class Record(BaseModel):
        amount: int

    monkeypatch.setattr("backend.repositories.base._orm_to_dict", lambda row: {"amount": PRIVATE})
    repository = BaseRepository(None, None, Record, "missing")
    with caplog.at_level(logging.ERROR), pytest.raises(ValidationError):
        repository._to_pydantic(SimpleNamespace())
    output = "\n".join(JSONFormatter().format(record) for record in caplog.records)
    assert PRIVATE not in output
    assert "ValidationError" in output and "Record" in output


def test_cyclic_exception_causes_finish_without_rendering_messages():
    first, second = RuntimeError(PRIVATE), ValueError(PRIVATE)
    first.__cause__, second.__cause__ = second, first
    diagnostic = exception_diagnostic(first)
    assert [entry["type"] for entry in diagnostic["exception_chain"]] == ["RuntimeError", "ValueError"]
    assert PRIVATE not in str(diagnostic)
