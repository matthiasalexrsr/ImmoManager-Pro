"""Rent-history writes on independent PostgreSQL connections, including failure rollback."""

import threading
from datetime import date

import pytest
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401
from test_rent_payments import seed, user

from backend import auth
from backend.models import InsuranceCreate, RentAdjustmentCreate, RentAdjustmentPatch, UnitCreate
from backend.repositories import SQLAlchemyStore
from backend.services import rent_adjustments
from backend.services.maintenance_rows import Rows
from backend.services.office_records import save_record
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import ValidationError


def _create(engine, *, applied=False):
    owner, _ = user("eigentuemer")
    account = auth.get_user_by_id(owner.id)
    assert account is not None
    scope = scope_from_user(account)
    with Session(engine) as db:
        target = SQLAlchemyStore(db)
        estate = seed(target)
        with scope_context(scope):
            adjustment = rent_adjustments.save_adjustment(target, RentAdjustmentCreate(
                contract_id=estate["contract"].id, adjustment_type="index", effective_date=date(2026, 2, 1),
                previous_rent=500, new_rent=550, status="applied" if applied else "pending"))
    return estate, adjustment, scope


def test_concurrent_applications_from_two_accounts_create_one_period(postgres):  # noqa: F811
    engine, _ = postgres
    estate, adjustment, first_scope = _create(engine)
    second, _ = user("eigentuemer")
    second_account = auth.get_user_by_id(second.id)
    assert second_account is not None
    second_scope = scope_from_user(second_account)
    gate = threading.Barrier(2)
    outcomes, errors = [], []

    def apply(scope):
        with Session(engine) as db, scope_context(scope):
            try:
                gate.wait(timeout=10)
                outcomes.append(rent_adjustments.apply_adjustment(SQLAlchemyStore(db), adjustment.id)[0].status)
            except BaseException as error:
                errors.append(error)

    workers = [threading.Thread(target=apply, args=(scope,)) for scope in (first_scope, second_scope)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
        assert not worker.is_alive()
    assert errors == []
    assert outcomes == ["applied", "applied"]
    with Session(engine) as db:
        periods = SQLAlchemyStore(db).list_contract_rent_periods(estate["contract"].id)
        assert len(periods) == 2
        assert [period.cold_rent for period in periods] == [500, 550]


def test_failed_edit_rolls_back_adjustment_and_period_on_postgres(postgres, monkeypatch):  # noqa: F811
    engine, _ = postgres
    estate, adjustment, scope = _create(engine, applied=True)
    with Session(engine) as db:
        original = SQLAlchemyStore(db).get_rent_adjustment(adjustment.id)
        periods = SQLAlchemyStore(db).list_contract_rent_periods(estate["contract"].id)
    update = Rows.update

    def fail_after_history(self, table, key, **changes):
        result = update(self, table, key, **changes)
        if table == "contract_rent_periods":
            raise ValidationError("Prüffehler nach dem Mietverlauf")
        return result

    monkeypatch.setattr(Rows, "update", fail_after_history)
    with Session(engine) as db, scope_context(scope), pytest.raises(ValidationError, match="Prüffehler"):
        rent_adjustments.save_adjustment(SQLAlchemyStore(db), RentAdjustmentPatch(new_rent=600),
                                         adjustment.id, partial=True)
    with Session(engine) as db:
        target = SQLAlchemyStore(db)
        assert target.get_rent_adjustment(adjustment.id) == original
        assert target.list_contract_rent_periods(estate["contract"].id) == periods


def test_office_assignment_is_validated_before_writing_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    estate, _, scope = _create(engine)
    with Session(engine) as db:
        target = SQLAlchemyStore(db)
        second = seed(target, number="MV-2")
        unit = target.create_unit(UnitCreate(property_id=second["prop"].id, label="Weitere Einheit", unit_type="flat"))
    with Session(engine) as db, scope_context(scope), pytest.raises(ValidationError, match="Einheit gehört"):
        save_record(SQLAlchemyStore(db), "insurances", InsuranceCreate(
            property_id=estate["prop"].id, unit_id=unit.id, insurance_type="building", provider="Versicherung"))
    with Session(engine) as db:
        assert SQLAlchemyStore(db).list_insurances() == []
