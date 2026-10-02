"""Required integration behavior; read-only probes of the live G06 source.

Run from work/contract-lifecycle with --noconftest -p backend.tests.conftest
against this absolute file. Only synthetic independent Memory/SQLite fixtures
are used; these regressions intentionally fail while Root hooks are absent.
"""

import pytest

from backend.models import ContractPatch, PropertyCreate, RentChargeCreate
from backend.services import contract_lifecycle as lifecycle
from backend.storage import ValidationError
from backend.tests import test_contract_lifecycle as fixtures

active = fixtures.active


def accepted(box):
    draft, _ = fixtures.create(box)
    reviewed = lifecycle.review_draft(box.store, box.contract.id, draft["id"], fixtures.command(draft, "review"), "actor")
    return lifecycle.confirm_draft(box.store, box.contract.id, draft["id"], fixtures.confirmation(reviewed), "actor")


def test_confirmed_end_cannot_be_cleared_by_ordinary_patch(active):
    row = accepted(active)
    assert row["state"] == "pending_effective"
    with pytest.raises(ValidationError):
        active.store._patch_entity("contract", active.contract.id, ContractPatch(end_date=None))
    assert str(active.store.get_contract(active.contract.id).end_date) == "2026-11-30"


def test_future_rent_month_cannot_be_added_after_confirm(active):
    accepted(active)
    valid = RentChargeCreate(contract_id=active.contract.id, month="2026-11", cold_rent=100,
                             due_date="2026-12-15")
    # An explicitly known November service period may be payable in December.
    active.store.create_rent_charge(valid)
    with pytest.raises(ValidationError):
        active.store.create_rent_charge(valid.model_copy(update={"month": "2026-12"}))
    assert [charge.month for charge in active.store.list_rent_charges()] == ["2026-11"]


def test_portfolio_reparent_cannot_break_confirmed_history(active):
    row = accepted(active)
    foreign = next(portfolio for portfolio in active.store.list_portfolios() if portfolio.id != active.p.id)
    values = active.property.model_dump(exclude={"id", "created_at", "updated_at"})
    with pytest.raises(ValidationError):
        active.store.update_property(active.property.id, PropertyCreate(**{**values, "portfolio_id": foreign.id}))
    assert lifecycle.get_draft(active.store, active.contract.id, row["id"], "actor")["id"] == row["id"]


def test_memory_reset_preserves_subjects_of_durable_lifecycle(active):
    if active.db is not None:
        pytest.skip("The separate SQL preflight test must assert zero DML, not a late trigger error")
    row = accepted(active)
    with pytest.raises(ValidationError):
        active.store.clear_all()
    assert active.store.get_contract(active.contract.id).id == active.contract.id
    assert lifecycle.get_draft(active.store, active.contract.id, row["id"], "actor")["id"] == row["id"]
