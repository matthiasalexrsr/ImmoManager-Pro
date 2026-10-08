"""Service contracts on a real PostgreSQL server: migration, constraints, portfolio boundary,
concurrent cost transfer and reminder job.

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
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContactCreate,
    PortfolioCreate,
    PropertyCreate,
)
from backend.models_service_contracts import (
    CostTransferRequest,
    InvoiceLinkRequest,
    ServiceContractCreate,
    ServiceContractCreateRequest,
)
from backend.repositories import SQLAlchemyStore
from backend.services import service_contracts as service
from backend.services.jobs import service_contract_deadlines as reminders
from backend.services.jobs.core import JobRunner, SqlJobStore
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import ValidationError

PREVIOUS = "f3b9c1d7e2a5"


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _seed(engine) -> dict:
    seed = _store(engine)
    north = seed.create_portfolio(PortfolioCreate(name="Nord"))
    south = seed.create_portfolio(PortfolioCreate(name="Süd"))
    house_n = seed.create_property(PropertyCreate(portfolio_id=north.id, name="Nordhaus", property_type="residential"))
    house_s = seed.create_property(PropertyCreate(portfolio_id=south.id, name="Südhaus", property_type="residential"))
    provider = seed.create_contact(ContactCreate(contact_type="supplier", company_name="Stadtwerke"))
    seed.db.close()
    return {"north": north, "south": south, "house_n": house_n, "house_s": house_s, "provider": provider}


def _request(seeded, *houses, **fields) -> ServiceContractCreateRequest:
    body = {"contract_type": "caretaker", "title": "Hauswart", "provider_contact_id": seeded["provider"].id,
            "start_date": "2025-01-01", "minimum_term_months": 24, "renewal_mode": "fixed", "renewal_months": 12,
            "notice_period_value": 3, "notice_period_unit": "month", "recoverable": True,
            "locations": [{"property_id": seeded[house].id} for house in houses]}
    body.update(fields)
    return ServiceContractCreateRequest.model_validate(body)


def _staff_scope(seeded):
    user = auth.register_user("nora", "nora@example.com", "Nora", "Secret123", "verwalter",
                              portfolio_access="selected", portfolio_ids=[seeded["north"].id])
    stored = auth.get_user_by_id(user.id)
    assert stored is not None
    return scope_from_user(stored)


def test_service_contract_migration_on_postgres(postgres):  # noqa: F811
    engine, config = postgres
    seeded = _seed(engine)
    inspector = sa.inspect(engine)
    keys = {(k["constrained_columns"][0], k["referred_table"], k["options"].get("ondelete"))
            for table in ("service_contracts", "service_contract_locations", "service_contract_invoices",
                          "service_contract_payments") for k in inspector.get_foreign_keys(table)}
    assert {("provider_contact_id", "contacts", "RESTRICT"), ("service_contract_id", "service_contracts", "CASCADE"),
            ("meter_id", "meters", "SET NULL"), ("invoice_id", "invoices", "RESTRICT"),
            ("booking_id", "bookings", "CASCADE")} <= keys
    assert any(i["name"] == "uq_cost_items_service_contract_invoice" and i["unique"]
               for i in inspector.get_indexes("cost_items"))
    target = _store(engine)
    contract = service.create_contract(target, _request(seeded, "house_n"))
    with pytest.raises(RuntimeError, match="service contracts"):
        command.downgrade(config, PREVIOUS)
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM service_contracts WHERE id = :id"), {"id": contract.id})
        assert connection.execute(sa.text("SELECT COUNT(*) FROM service_contract_locations")).scalar() == 0
    target.db.close()
    command.downgrade(config, PREVIOUS)
    assert "service_contracts" not in sa.inspect(engine).get_table_names()
    assert "service_contract_invoice_id" not in {c["name"] for c in sa.inspect(engine).get_columns("cost_items")}
    command.upgrade(config, "head")
    assert "service_contracts" in sa.inspect(engine).get_table_names()


def test_portfolio_boundary_of_service_contracts_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    owner = _store(engine)
    shared = service.create_contract(owner, _request(seeded, "house_n", "house_s", title="Gemeinsam"))
    south = service.create_contract(owner, _request(seeded, "house_s", title="Süd"))
    owner.db.close()
    scope = _staff_scope(seeded)
    staff = _store(engine)
    with scope_context(scope):
        rows = service.list_view(staff, as_of=date(2026, 6, 1))
        assert [r["title"] for r in rows] == ["Gemeinsam"]
        assert [loc["property_id"] for loc in rows[0]["locations"]] == [seeded["house_n"].id]
        assert service.detail_view(staff, shared.id, date(2026, 6, 1))["restricted"] is True
        with pytest.raises(Exception):
            staff.get_service_contract(south.id)
        data = ServiceContractCreate.model_validate({**shared.model_dump(), "title": "Übernommen"})
        with pytest.raises(HTTPException) as refused:
            service.update_contract(staff, shared.id, data)
        assert refused.value.status_code == 403
        staff.db.rollback()
        # the raw write is fenced too: the guard checks every location, not the service layer
        with pytest.raises(HTTPException):
            staff.update_service_contract(shared.id, data)
        staff.db.rollback()
        own = service.create_contract(staff, _request(seeded, "house_n", title="Eigener"))
        assert service.detail_view(staff, own.id, date(2026, 6, 1))["restricted"] is False
        with pytest.raises((HTTPException, ValidationError)):
            service.create_contract(staff, _request(seeded, "house_n", "house_s", title="Fremd"))
        staff.db.rollback()
    staff.db.close()
    check = _store(engine)
    assert sorted(c.title for c in check.list_service_contracts()) == ["Eigener", "Gemeinsam", "Süd"]
    assert check.get_service_contract(shared.id).title == "Gemeinsam"
    check.db.close()


def test_concurrent_transfers_of_one_bill_create_one_cost_item_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    setup = _store(engine)
    contract = service.create_contract(setup, _request(seeded, "house_n"))
    service.add_bill(setup, contract.id, InvoiceLinkRequest.model_validate({
        "period_start": "2026-01-01", "period_end": "2026-12-31",
        "invoice": {"supplier": "Hauswart", "invoice_date": "2027-01-15", "net_amount": 300, "gross_amount": 300}}))
    period = setup.create_billing_period(BillingPeriodCreate(property_id=seeded["house_n"].id, label="BK 2026",
                                                             start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    key = setup.create_allocation_key(AllocationKeyCreate(property_id=seeded["house_n"].id, name="Fläche",
                                                          key_type="area_sqm"))
    setup.db.close()
    request = CostTransferRequest(billing_period_id=period.id, allocation_key_id=key.id)
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def transfer():
        target = _store(engine)
        try:
            barrier.wait()
            result = service.transfer_costs(target, contract.id, request)
            outcomes.append("created" if result["created"] else "skipped")
        except ValidationError:
            outcomes.append("refused")
        finally:
            target.db.close()

    threads = [threading.Thread(target=transfer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert outcomes.count("created") == 1 and len(outcomes) == 4
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT amount FROM cost_items")).scalars().all()
    assert [float(value) for value in rows] == [300.0]


def test_deadline_reminders_once_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    setup = _store(engine)
    service.create_contract(setup, _request(seeded, "house_n"))      # notice deadline 30.09.2026
    setup.db.close()
    jobs = SqlJobStore(engine)
    for day in ("2026-09-05", "2026-09-06"):
        jobs.enqueue(reminders.KIND, f"{reminders.KIND}@{day}", {"as_of": day})
    workers = [JobRunner(jobs, {reminders.KIND: reminders.make_handler()}, owner=f"w{n}") for n in range(3)]
    threads = [threading.Thread(target=worker.run_until_idle) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    with engine.connect() as connection:
        tasks = connection.execute(sa.text("SELECT title, due_date FROM tasks")).all()
        notes = connection.execute(sa.text(
            "SELECT COUNT(*) FROM notifications WHERE notification_type = 'service_contract_deadline'")).scalar()
    assert [(title, str(due)) for title, due in tasks] == [("Kündigungsfrist: Hauswart", "2026-09-30")]
    assert notes == 1
