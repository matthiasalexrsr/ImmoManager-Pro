"""Dunning on a real PostgreSQL server: migration and guarded downgrade, partial unique indexes,
concurrent finalization of one letter, the proposing job with several workers, portfolio boundary.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL (see test_document_versions_postgres.py).
"""

import threading
from datetime import date

import pytest
import sqlalchemy as sa
from alembic import command
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401  (fixture: own database per test)

from backend import auth
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.models_dunning import BaseRateRequest, FinalizeRequest, RunRequest, RunScope
from backend.repositories import SQLAlchemyStore
from backend.services import dunning as service
from backend.services.jobs.core import JobRunner, SqlJobStore
from backend.services.jobs.scheduler import ESCALATION_KIND, escalation_handler
from backend.services.portfolio_scope import scope_context, scope_from_user

PREVIOUS = "5e8b2d4f7a19"


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _seed(engine) -> dict:
    seed = _store(engine)
    found: dict = {}
    for name in ("Nord", "Süd"):
        portfolio = seed.create_portfolio(PortfolioCreate(name=name, owner_name=f"HV {name}"))
        prop = seed.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"{name}haus",
                                                   property_type="residential"))
        unit = seed.create_unit(UnitCreate(property_id=prop.id, label="W1", unit_type="residential", cold_rent=1000))
        tenant = seed.create_tenant(TenantCreate(full_name=f"Mieter {name}"))
        contract = seed.create_contract(ContractCreate(contract_number=f"V-{name}", property_id=prop.id,
                                                       unit_id=unit.id, tenant_id=tenant.id,
                                                       start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)))
        found[name] = {"portfolio": portfolio, "contract": contract}
    seed.db.close()
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    found["owner"] = owner.id
    service.add_base_rate(_store(engine), BaseRateRequest(valid_from=date(2026, 1, 1), rate_percent=1.27), owner.id)
    return found


def _draft(engine, seeded, name="Nord", as_of=date(2026, 7, 10)) -> dict:
    target = _store(engine)
    scope = RunScope(contract_id=seeded[name]["contract"].id, as_of=as_of)
    preview = service.preview(target, scope, seeded["owner"])
    run = service.create_run(target, RunRequest(**scope.model_dump(), command_key=f"run-{name}-{as_of}",
                                                preview_hash=preview["preview_hash"]), seeded["owner"])
    target.db.close()
    return service.letter_detail(_store(engine), run["letters"][0]["id"], seeded["owner"])


def test_dunning_migration_indexes_and_guarded_downgrade_on_postgres(postgres):  # noqa: F811
    engine, config = postgres
    seeded = _seed(engine)
    inspector = sa.inspect(engine)
    keys = {(table, k["constrained_columns"][0], k["referred_table"], k["options"].get("ondelete"))
            for table in ("dunning_cases", "dunning_case_items", "dunning_letters", "dunning_replies")
            for k in inspector.get_foreign_keys(table)}
    assert {("dunning_cases", "contract_id", "contracts", "CASCADE"),
            ("dunning_case_items", "receivable_id", "receivables", "SET NULL"),
            ("dunning_letters", "document_id", "documents", "RESTRICT"),
            ("dunning_replies", "case_id", "dunning_cases", "SET NULL")} <= keys
    letter = _draft(engine, seeded)
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:     # one open case per contract
        connection.execute(sa.text("INSERT INTO dunning_cases (id, contract_id, reference, opened_on) "
                                   "VALUES ('x', :c, 'M-2026-XXXXXXXX', '2026-07-10')"),
                           {"c": seeded["Nord"]["contract"].id})
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:     # one living letter per stage
        connection.execute(sa.text(
            "INSERT INTO dunning_letters (id, case_id, contract_id, stage, letter_date, payment_deadline, principal, "
            "total, content, draft_hash) SELECT 'l2', case_id, contract_id, stage, letter_date, payment_deadline, "
            "principal, total, content, draft_hash FROM dunning_letters WHERE id = :id"), {"id": letter["id"]})
    with pytest.raises(RuntimeError, match="dunning"):
        command.downgrade(config, PREVIOUS)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() != PREVIOUS
    with engine.begin() as connection:
        for table in ("dunning_cases", "dunning_runs", "dunning_base_rates"):   # cases cascade to their parts
            connection.execute(sa.text(f"DELETE FROM {table}"))
    command.downgrade(config, PREVIOUS)
    assert not {"dunning_cases", "dunning_letters"} & set(sa.inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert "dunning_outbox" in sa.inspect(engine).get_table_names()


def test_concurrent_finalizations_of_one_letter_archive_one_original_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    target = _store(engine)
    first = _draft(engine, seeded, as_of=date(2026, 7, 10))
    service.finalize_letter(target, first["id"], FinalizeRequest(
        command_key="fin-first-1", draft_hash=first["draft_hash"], confirmed=True), seeded["owner"])
    target.db.close()
    second = _draft(engine, seeded, as_of=date(2026, 7, 25))
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def finalize(number: int):
        target = _store(engine)
        try:
            barrier.wait()
            service.finalize_letter(target, second["id"], FinalizeRequest(
                command_key=f"fin-race-{number}", draft_hash=second["draft_hash"], confirmed=True), seeded["owner"])
            outcomes.append("final")
        except HTTPException as error:
            outcomes.append(str(error.status_code))
        finally:
            target.db.close()

    threads = [threading.Thread(target=finalize, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert outcomes.count("final") == 1 and sorted(outcomes) == ["409", "409", "409", "final"]
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM documents WHERE document_type = 'dunning_letter'")).scalar() == 2
        assert sorted(float(v) for v in connection.execute(sa.text(
            "SELECT amount_due FROM receivables")).scalars()) == [2.5, 3.78]
        assert connection.execute(sa.text("SELECT stage FROM dunning_cases")).scalar() == 2


def test_the_proposal_job_with_three_workers_notifies_once_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    _seed(engine)
    jobs = SqlJobStore(engine)
    for day in ("2026-07-10", "2026-07-11"):
        jobs.enqueue(ESCALATION_KIND, f"{ESCALATION_KIND}@{day}", {"as_of": day})
    workers = [JobRunner(jobs, {ESCALATION_KIND: escalation_handler}, owner=f"w{n}") for n in range(3)]
    threads = [threading.Thread(target=worker.run_until_idle) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    with engine.connect() as connection:
        titles = connection.execute(sa.text(
            "SELECT title FROM notifications WHERE notification_type = 'dunning_proposal' ORDER BY title")).scalars()
        assert list(titles) == ["Mahnvorschlag: Zahlungserinnerung – Vertrag V-Nord",
                                "Mahnvorschlag: Zahlungserinnerung – Vertrag V-Süd"]
        assert connection.execute(sa.text("SELECT COUNT(*) FROM dunning_letters")).scalar() == 0


def test_the_portfolio_boundary_of_dunning_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    north = _draft(engine, seeded, "Nord")
    south = _draft(engine, seeded, "Süd")
    staff = auth.register_user("nora", "nora@example.com", "Nora", "Secret123", "buchhaltung",
                               portfolio_access="selected", portfolio_ids=[seeded["Nord"]["portfolio"].id])
    stored = auth.get_user_by_id(staff.id)
    assert stored is not None
    target = _store(engine)
    with scope_context(scope_from_user(stored)):
        rows = service.overview(target, staff.id)["items"]
        assert [r["id"] for r in rows] == [north["case_id"]]
        for call in (lambda: service.contract_file(target, seeded["Süd"]["contract"].id, staff.id),
                     lambda: service.letter_detail(target, south["id"], staff.id),
                     lambda: service.timeline(target, south["case_id"], staff.id)):
            with pytest.raises(HTTPException) as refused:
                call()
            assert refused.value.status_code == 404
        final = service.finalize_letter(target, north["id"], FinalizeRequest(
            command_key="nora-fin-1", draft_hash=north["draft_hash"], confirmed=True), staff.id)
        assert final["status"] == "final"
    target.db.close()
