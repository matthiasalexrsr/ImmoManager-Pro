"""Re-letting projects on a real PostgreSQL server: the flow, one open project per unit under
concurrent starts, the deletion of applicants and the migration's downgrade guard.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL pointing at a disposable loopback PostgreSQL server with
CREATE DATABASE permission. Each test owns a new immoqa_reletting_<uuid> database and drops only it.
"""

import os
import threading
import uuid
from datetime import date, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker
from test_deposits_postgres import MIGRATIONS

import backend.models  # noqa: F401 (register the UI contract columns)
from backend import auth
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, UnitCreate
from backend.models_reletting import (
    AcceptRequest,
    ApplicantInput,
    CloseRequest,
    PurgeRequest,
    RelettingStart,
    ViewingInput,
)
from backend.repositories import SQLAlchemyStore
from backend.services import reletting as service

PARENT = "f022a1b2c001"


@pytest.fixture
def postgres(monkeypatch):
    admin_url = os.getenv("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for real PostgreSQL re-letting tests")
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL re-letting tests require an explicitly configured loopback server")
    name = f"immoqa_reletting_{uuid.uuid4().hex}"
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    test_url = url.set(database=name)
    engine = sa.create_engine(test_url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    monkeypatch.setenv("DATABASE_URL", test_url.render_as_string(hide_password=False))
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        command.upgrade(config, "head")
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(engine)))
        yield engine, config
    finally:
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _unit(engine):
    target = _store(engine)
    portfolio = target.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                 property_type="residential", city="Dresden"))
    unit = target.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="Wohnung", rooms=2,
                                         area_sqm=60, cold_rent=500, service_charge_advance=150))
    target.db.close()
    return prop, unit


def _call(operation, engine, *args):
    target = _store(engine)
    try:
        return operation(target, *args)
    finally:
        target.db.close()


def test_the_reletting_flow_and_the_deletion_of_applicants_on_postgres(postgres):
    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    prop, unit = _unit(engine)
    detail = _call(service.start, engine, RelettingStart(unit_id=unit.id), owner.id)
    project_id = detail["project"]["id"]
    assert detail["warm_rent"] == 650 and detail["project"]["deposit_amount"] == 1500
    detail = _call(service.add_applicant, engine, project_id, ApplicantInput(
        full_name="Anna Bergmann", email="anna@example.com", household_size=2, net_income=2600), owner.id)
    anna = detail["applicants"][0]
    detail = _call(service.add_applicant, engine, project_id, ApplicantInput(full_name="Bernd Krause",
                                                                             status="rejected"), owner.id)
    bernd = next(row for row in detail["applicants"] if row["full_name"] == "Bernd Krause")
    _call(service.add_viewing, engine, project_id, ViewingInput(lead_id=anna["id"],
                                                                scheduled_at=datetime(2026, 10, 24, 15, 30)), owner.id)
    with engine.begin() as connection:              # a shared note on the rejected applicant
        connection.execute(sa.text(
            "INSERT INTO change_history (id, entity_type, entity_id, field_name, new_value, changed_at) "
            "VALUES ('h1', 'lead', :id, 'notes', 'rief an', now())"), {"id": bernd["id"]})
    accepted = _call(service.accept, engine, project_id, AcceptRequest(lead_id=anna["id"]), owner.id)
    tenant_id = accepted["project"]["tenant_id"]
    assert accepted["contract_prefill"]["tenant_id"] == tenant_id and accepted["rent_applied"] is False
    purged, files = _call(service.purge, engine, project_id, PurgeRequest(lead_ids=[bernd["id"]], confirmed=True),
                          owner.id)
    assert purged["deleted"] == 1 and files == []
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM leads WHERE id = :id"), {"id": bernd["id"]}).scalar() == 0
        assert connection.execute(sa.text("SELECT COUNT(*) FROM change_history WHERE entity_id = :id"),
                                  {"id": bernd["id"]}).scalar() == 0
        assert connection.execute(sa.text("SELECT deleted_applicants FROM reletting_projects")).scalar() == 1
    target = _store(engine)
    contract = target.create_contract(ContractCreate(contract_number="MV-7", property_id=prop.id, unit_id=unit.id,
                                                     tenant_id=tenant_id, start_date=date(2026, 12, 1)))
    target.db.close()
    closed = _call(service.close, engine, project_id, CloseRequest(contract_id=contract.id), owner.id)
    assert closed["project"]["status"] == "closed"


def test_one_open_project_per_unit_under_concurrent_starts(postgres):
    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    _, unit = _unit(engine)
    gate = threading.Barrier(2)
    outcomes: list[str] = []

    def start():
        target = _store(engine)
        try:
            gate.wait(timeout=10)
            service.start(target, RelettingStart(unit_id=unit.id), owner.id)
            outcomes.append("started")
        except (HTTPException, sa.exc.IntegrityError):
            outcomes.append("refused")
        except BaseException as error:  # noqa: BLE001 - reported below
            outcomes.append(repr(error))
        finally:
            target.db.close()

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["refused", "started"], outcomes
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM reletting_projects WHERE status = 'open'")).scalar() == 1


def test_the_reletting_downgrade_refuses_while_projects_exist_on_postgres(postgres):
    engine, config = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    _, unit = _unit(engine)
    _call(service.start, engine, RelettingStart(unit_id=unit.id), owner.id)
    with pytest.raises(RuntimeError, match="re-letting projects"):
        command.downgrade(config, PARENT)
    assert "reletting_projects" in sa.inspect(engine).get_table_names()     # nothing changed
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM reletting_projects"))
        connection.execute(sa.text("UPDATE leads SET doc_income = TRUE"))
    command.downgrade(config, PARENT)                    # no lead exists, so no applicant detail is lost
    inspector = sa.inspect(engine)
    assert "reletting_projects" not in inspector.get_table_names()
    assert "project_id" not in {column["name"] for column in inspector.get_columns("leads")}
    command.upgrade(config, "head")
    assert "lead_attachments" in sa.inspect(engine).get_table_names()
