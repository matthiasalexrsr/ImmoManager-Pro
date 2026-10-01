"""Actual runtime registration, startup upgrade and fail-closed reset/imports."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from backend import auth
from backend.db.tax_models import AnnualTaxSourceORM
from backend.services import annual_tax_storage as service
from backend.services.data_transfer import TransferError, export_store_data, import_store_data
from backend.tests.test_annual_tax_projection import booking, preflight_command, profile_command, save_command
from backend.tests.test_annual_tax_projection import tax_store as tax_store  # noqa: F401 fixture


def test_registered_actual_application_requires_auth_and_fresh_sql_startup_creates_all_tax_tables(tax_store, monkeypatch):
    store, engine, portfolio, *_ = tax_store
    from backend.app import app
    from backend.db import session
    from backend.routers import annual_tax
    monkeypatch.setattr(session, "engine", engine)
    monkeypatch.setattr(annual_tax, "store", store)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    # Simulate a historical create_all installation whose cash already exists.
    cash = booking(tax_store, 12.34)
    with engine.begin() as db:
        for name in ("annual_tax_sources", "annual_tax_projections", "annual_tax_profiles"):
            db.exec_driver_sql("DROP TABLE " + name)
    session.create_tables()
    assert all(name in inspect(engine).get_table_names() for name in ("annual_tax_profiles", "annual_tax_projections", "annual_tax_sources"))
    assert store.get_booking(cash.id).amount == 12.34
    session.create_tables()  # Idempotent ordinary restart, no historic mutation.
    actor = auth.register_user("tax-integration", "tax@example.test", "Synthetic", "StrongPass123!", "buchhaltung", portfolio_access="selected", portfolio_ids=[portfolio.id])
    token = {"Authorization": "Bearer " + auth.create_access_token(actor.id)}
    with TestClient(app) as client:
        path = "/api/v1/reports/annual-tax"
        assert client.get(path + "/options", params={"portfolio_id": portfolio.id}).status_code == 401
        assert client.get(path + "/options", params={"portfolio_id": portfolio.id}, headers=token).status_code == 200
        response = client.post(path + "/profiles", json=profile_command(tax_store).model_dump(mode="json"), headers=token)
        assert response.status_code == 201, response.text
        assert response.json()["actor_id"] == actor.id


@pytest.mark.parametrize("with_projection", [False, True])
def test_saved_profiles_or_sources_prevent_clear_all_and_partial_replace_before_any_mutation(tax_store, with_projection):
    store, _, portfolio, *_ = tax_store
    source = booking(tax_store, 100)
    version = service.create_profile(store, profile_command(tax_store), "actor")
    saved = None
    if with_projection:
        command = preflight_command(version)
        saved = service.create_projection(store, save_command(command, service.preflight(store, command)), "actor")
    before = export_store_data(store, "synthetic-test")
    if hasattr(store, "db"):
        # Observe every SQL mutation; refusal must happen before the first DML.
        from sqlalchemy import event
        statements = []
        @event.listens_for(store.db.get_bind(), "before_cursor_execute")
        def writes(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER"}:
                statements.append(statement)
    else:
        original = deepcopy(object.__getattribute__(store, "__dict__"))
    with pytest.raises(ValueError, match="vollständige Datenbanksicherung"):
        store.clear_all()
    with pytest.raises(TransferError, match="vollständige Datenbanksicherung"):
        import_store_data(store, before, replace_existing=True)
    if hasattr(store, "db"):
        assert statements == []
        assert store.db.scalar(select(AnnualTaxSourceORM.id)) is not None if saved else store.db.scalar(select(AnnualTaxSourceORM.id)) is None
    else:
        assert object.__getattribute__(store, "__dict__") == original
    assert store.get_booking(source.id).amount == 100
    assert service.get_profile(store, version["id"]) == version
    if saved:
        assert len(list(service.saved_sources(store, saved["id"]))) == 1
    # Unknown source tables are not accepted in a business-JSON import either.
    invalid = before | {"annual_tax_sources": [{"source_json": "{}"}]}
    with pytest.raises(TransferError):
        import_store_data(store, invalid, replace_existing=False)
    assert service.list_profiles(store, portfolio.id)["total"] == 1
