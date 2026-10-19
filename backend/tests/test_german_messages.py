"""Messages people read are German: server errors, validation texts and coded module messages."""

import ast
import pathlib
import re
from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.datev_models import DatevPreviewCreate
from backend.exceptions import readable, register_exception_handlers

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ENGLISH = {"the", "is", "not", "must", "be", "for", "to", "of", "no", "found", "invalid", "required", "already",
           "cannot", "only", "and", "or", "with", "this", "that", "are", "has", "have", "missing", "unknown",
           "failed", "please", "allowed", "exists", "does", "an", "a", "needs", "need", "should", "denied"}
GERMAN = {"der", "die", "das", "nicht", "ist", "sind", "bitte", "kein", "keine", "ein", "eine", "und", "oder",
          "mit", "für", "fehlt", "muss", "darf", "wird", "wurde", "vorhanden", "gefunden", "zu", "zum", "zur",
          "von", "auf"}
# framework texts the error handler replaces with German ones
REPLACED = {"Not Found"}


def test_coded_messages_show_their_german_text():
    assert readable("annual_tax_profile_not_found: Steuerprofil nicht gefunden.") == "Steuerprofil nicht gefunden."
    assert readable("DATEV source_changed: Bitte eine neue Vorschau erstellen.") == "DATEV: Bitte eine neue Vorschau erstellen."
    # ordinary sentences with a colon stay as they are
    assert readable("Wiederherstellung abgebrochen – keine ImmoManager-Datenbank: x.db") == \
        "Wiederherstellung abgebrochen – keine ImmoManager-Datenbank: x.db"
    assert readable("Es fehlt: Kaltmiete") == "Es fehlt: Kaltmiete"


def test_the_error_response_carries_the_text_and_the_log_the_code(caplog):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/coded")
    def coded():
        raise HTTPException(409, "annual_tax_source_changed: Die Vorprüfung erneut ansehen und bestätigen.")

    with caplog.at_level("WARNING"):
        response = TestClient(app).get("/coded")
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Die Vorprüfung erneut ansehen und bestätigen."
    assert "annual_tax_source_changed" in caplog.text


def test_datev_dates_are_explained_in_german():
    with pytest.raises(ValidationError, match="Startdatum muss vor dem Enddatum"):
        DatevPreviewCreate(profile_version_id="p", idempotency_key="k", start_date=date(2026, 5, 1),
                           end_date=date(2026, 4, 1))


def _words(text: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[A-Za-zÄÖÜäöüß]+", text)]


def _texts(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        yield "".join(part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str))


def _validator(stack: list[ast.AST]) -> bool:
    def named(decorator: ast.AST) -> str:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        return getattr(target, "id", getattr(target, "attr", ""))
    return any(isinstance(node, ast.FunctionDef) and any(named(d) in ("field_validator", "model_validator", "validator")
                                                         for d in node.decorator_list) for node in stack)


def test_no_english_message_reaches_people():
    """HTTP details, validator errors and store errors are read by people; none may be English."""
    found = []
    for path in sorted(BACKEND.rglob("*.py")):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))

        def visit(node: ast.AST, stack: list[ast.AST]) -> None:
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name in ("HTTPException", "ValidationError", "NotFoundError") or (name == "ValueError" and _validator(stack)):
                    arguments = list(node.args) + [k.value for k in node.keywords if k.arg in ("detail", "message")]
                    for argument in arguments:
                        for text in _texts(argument):
                            words = _words(text)
                            english = sum(word in ENGLISH for word in words)
                            if (text not in REPLACED and english and english > sum(word in GERMAN for word in words)
                                    and not re.search(r"[äöüÄÖÜß]", text)):
                                found.append(f"{path.relative_to(BACKEND.parent)}:{node.lineno}: {text[:80]}")
            for child in ast.iter_child_nodes(node):
                visit(child, [*stack, node])

        visit(tree, [])
    assert not found, "\n".join(found)
