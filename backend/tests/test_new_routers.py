"""Comprehensive tests for the 6 new routers: tax_rates, rent_adjustments,
handover_protocols, budgets, escalation, and history.

Tests call router functions directly (no HTTP client) following existing conventions.
Query() defaults are not resolved when calling functions directly, so
skip/limit and filter params must always be passed explicitly.
"""

from datetime import date, datetime

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.models import (
    BudgetCreate,
    BudgetPatch,
    ChangeHistoryEntry,
    ContractCreate,
    EscalationRuleCreate,
    EscalationRulePatch,
    HandoverProtocolCreate,
    HandoverProtocolPatch,
    MeterReadingCreate,
    PortfolioCreate,
    PropertyCreate,
    RentAdjustmentCreate,
    RentAdjustmentPatch,
    TaskCreate,
    TaxRateCreate,
    TaxRatePatch,
    TenantCreate,
    UnitCreate,
)
from backend.routers import (
    budgets,
    escalation,
    handover_protocols,
    history,
    rent_adjustments,
    tax_rates,
)

# Default pagination values (Query defaults aren't resolved outside FastAPI).
S, L = 0, 100


# -- Wrapper helpers for list endpoints --

def _list_tax_rates(**kw):
    return tax_rates.list_tax_rates(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
    )


def _list_rent_adjustments(**kw):
    return rent_adjustments.list_rent_adjustments(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        contract_id=kw.get("contract_id"), adjustment_type=kw.get("adjustment_type"),
    )


def _list_handover_protocols(**kw):
    return handover_protocols.list_handover_protocols(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        contract_id=kw.get("contract_id"), unit_id=kw.get("unit_id"),
        protocol_type=kw.get("protocol_type"),
    )


def _list_meter_readings(**kw):
    return handover_protocols.list_all_meter_readings(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        handover_id=kw.get("handover_id"), meter_type=kw.get("meter_type"),
    )


def _list_budgets(**kw):
    return budgets.list_budgets(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"), year=kw.get("year"),
        category=kw.get("category"),
    )


def _list_rules(**kw):
    return escalation.list_rules(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        entity_type=kw.get("entity_type"), is_active=kw.get("is_active"),
    )


def _list_history(**kw):
    return history.list_history(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        entity_type=kw.get("entity_type"), entity_id=kw.get("entity_id"),
    )


def _clear_store() -> None:
    """Clear all store collections used by these routers."""
    for collection in (
        store.tax_rates,
        store.rent_adjustments,
        store.handover_protocols,
        store.meter_readings,
        store.budgets,
        store.escalation_rules,
        store.change_history,
        store.portfolios,
        store.properties,
        store.units,
        store.tenants,
        store.contracts,
        store.tasks,
        store.notifications,
    ):
        collection.clear()


def _create_contract_chain():
    """Helper: create portfolio -> property -> unit -> tenant -> contract.

    Returns (property_id, unit_id, tenant_id, contract_id).
    """
    pf = store.create_portfolio(PortfolioCreate(name="Test Portfolio"))
    prop = store.create_property(
        PropertyCreate(portfolio_id=pf.id, name="Haus", property_type="residential"),
    )
    unit = store.create_unit(
        UnitCreate(property_id=prop.id, label="W1", unit_type="apartment"),
    )
    tenant = store.create_tenant(TenantCreate(full_name="Max Mustermann"))
    contract = store.create_contract(
        ContractCreate(
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            contract_number="V-001",
            start_date=date(2024, 1, 1),
        ),
    )
    return prop.id, unit.id, tenant.id, contract.id


# ---------------------------------------------------------------------------
# Tax Rates
# ---------------------------------------------------------------------------

class TestTaxRates:
    def setup_method(self) -> None:
        _clear_store()

    def test_list_empty(self) -> None:
        assert _list_tax_rates() == []

    def test_create(self) -> None:
        tr = tax_rates.create_tax_rate(TaxRateCreate(name="Regelsteuersatz", rate=19.0))
        assert tr.name == "Regelsteuersatz"
        assert tr.rate == 19.0
        assert tr.id

    def test_list_returns_created(self) -> None:
        tax_rates.create_tax_rate(TaxRateCreate(name="Normal", rate=19.0))
        tax_rates.create_tax_rate(TaxRateCreate(name="Ermäßigt", rate=7.0))
        assert len(_list_tax_rates()) == 2

    def test_list_pagination(self) -> None:
        for i in range(5):
            tax_rates.create_tax_rate(TaxRateCreate(name=f"Rate{i}", rate=float(i)))
        assert len(_list_tax_rates(skip=0, limit=2)) == 2
        assert len(_list_tax_rates(skip=3, limit=10)) == 2
        assert len(_list_tax_rates(skip=10, limit=10)) == 0

    def test_get(self) -> None:
        tr = tax_rates.create_tax_rate(TaxRateCreate(name="Test", rate=10.0))
        fetched = tax_rates.get_tax_rate(tr.id)
        assert fetched.id == tr.id
        assert fetched.name == "Test"

    def test_get_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tax_rates.get_tax_rate("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update(self) -> None:
        tr = tax_rates.create_tax_rate(TaxRateCreate(name="Old", rate=5.0))
        updated = tax_rates.update_tax_rate(tr.id, TaxRateCreate(name="New", rate=7.0))
        assert updated.name == "New"
        assert updated.rate == 7.0
        assert updated.id == tr.id

    def test_update_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tax_rates.update_tax_rate("nonexistent", TaxRateCreate(name="X", rate=1.0))
        assert exc_info.value.status_code == 404

    def test_patch(self) -> None:
        tr = tax_rates.create_tax_rate(TaxRateCreate(name="Patch", rate=19.0, description="orig"))
        patched = tax_rates.patch_tax_rate(tr.id, TaxRatePatch(description="updated"))
        assert patched.description == "updated"
        assert patched.name == "Patch"  # unchanged

    def test_patch_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tax_rates.patch_tax_rate("nonexistent", TaxRatePatch(name="X"))
        assert exc_info.value.status_code == 404

    def test_delete(self) -> None:
        tr = tax_rates.create_tax_rate(TaxRateCreate(name="Del", rate=1.0))
        tax_rates.delete_tax_rate(tr.id)
        assert _list_tax_rates() == []

    def test_delete_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tax_rates.delete_tax_rate("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Rent Adjustments
# ---------------------------------------------------------------------------

class TestRentAdjustments:
    def setup_method(self) -> None:
        _clear_store()
        self.prop_id, self.unit_id, self.tenant_id, self.contract_id = _create_contract_chain()

    def _make_payload(self, **overrides):
        defaults = dict(
            contract_id=self.contract_id,
            adjustment_type="index",
            effective_date=date(2024, 6, 1),
            previous_rent=800.0,
            new_rent=850.0,
        )
        defaults.update(overrides)
        return RentAdjustmentCreate(**defaults)

    def test_list_empty(self) -> None:
        assert _list_rent_adjustments() == []

    def test_create(self) -> None:
        adj = rent_adjustments.create_rent_adjustment(self._make_payload())
        assert adj.contract_id == self.contract_id
        assert adj.new_rent == 850.0
        assert adj.id

    def test_list_returns_created(self) -> None:
        rent_adjustments.create_rent_adjustment(self._make_payload())
        rent_adjustments.create_rent_adjustment(self._make_payload(adjustment_type="stepped"))
        assert len(_list_rent_adjustments()) == 2

    def test_list_filter_contract_id(self) -> None:
        rent_adjustments.create_rent_adjustment(self._make_payload())
        assert len(_list_rent_adjustments(contract_id=self.contract_id)) == 1
        assert len(_list_rent_adjustments(contract_id="other")) == 0

    def test_list_filter_adjustment_type(self) -> None:
        rent_adjustments.create_rent_adjustment(self._make_payload(adjustment_type="index"))
        rent_adjustments.create_rent_adjustment(self._make_payload(adjustment_type="stepped"))
        assert len(_list_rent_adjustments(adjustment_type="index")) == 1
        assert len(_list_rent_adjustments(adjustment_type="stepped")) == 1

    def test_get(self) -> None:
        adj = rent_adjustments.create_rent_adjustment(self._make_payload())
        fetched = rent_adjustments.get_rent_adjustment(adj.id)
        assert fetched.id == adj.id

    def test_get_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            rent_adjustments.get_rent_adjustment("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update(self) -> None:
        adj = rent_adjustments.create_rent_adjustment(self._make_payload())
        updated = rent_adjustments.update_rent_adjustment(
            adj.id, self._make_payload(new_rent=900.0),
        )
        assert updated.new_rent == 900.0
        assert updated.id == adj.id

    def test_update_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            rent_adjustments.update_rent_adjustment("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_patch(self) -> None:
        adj = rent_adjustments.create_rent_adjustment(self._make_payload())
        patched = rent_adjustments.patch_rent_adjustment(adj.id, RentAdjustmentPatch(status="applied"))
        assert patched.status == "applied"
        assert patched.new_rent == 850.0  # unchanged

    def test_patch_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            rent_adjustments.patch_rent_adjustment("nonexistent", RentAdjustmentPatch(status="applied"))
        assert exc_info.value.status_code == 404

    def test_delete(self) -> None:
        adj = rent_adjustments.create_rent_adjustment(self._make_payload())
        rent_adjustments.delete_rent_adjustment(adj.id)
        assert _list_rent_adjustments() == []

    def test_delete_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            rent_adjustments.delete_rent_adjustment("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_invalid_contract(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            rent_adjustments.create_rent_adjustment(self._make_payload(contract_id="bad"))
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Handover Protocols
# ---------------------------------------------------------------------------

class TestHandoverProtocols:
    def setup_method(self) -> None:
        _clear_store()
        self.prop_id, self.unit_id, self.tenant_id, self.contract_id = _create_contract_chain()

    def _make_payload(self, **overrides):
        defaults = dict(
            contract_id=self.contract_id,
            unit_id=self.unit_id,
            protocol_type="move_in",
            protocol_date=date(2024, 1, 15),
        )
        defaults.update(overrides)
        return HandoverProtocolCreate(**defaults)

    def test_list_empty(self) -> None:
        assert _list_handover_protocols() == []

    def test_create(self) -> None:
        hp = handover_protocols.create_handover_protocol(self._make_payload())
        assert hp.contract_id == self.contract_id
        assert hp.protocol_type == "move_in"
        assert hp.id

    def test_list_returns_created(self) -> None:
        handover_protocols.create_handover_protocol(self._make_payload())
        handover_protocols.create_handover_protocol(self._make_payload(protocol_type="move_out"))
        assert len(_list_handover_protocols()) == 2

    def test_list_filter_contract_id(self) -> None:
        handover_protocols.create_handover_protocol(self._make_payload())
        assert len(_list_handover_protocols(contract_id=self.contract_id)) == 1
        assert len(_list_handover_protocols(contract_id="other")) == 0

    def test_list_filter_unit_id(self) -> None:
        handover_protocols.create_handover_protocol(self._make_payload())
        assert len(_list_handover_protocols(unit_id=self.unit_id)) == 1
        assert len(_list_handover_protocols(unit_id="other")) == 0

    def test_list_filter_protocol_type(self) -> None:
        handover_protocols.create_handover_protocol(self._make_payload(protocol_type="move_in"))
        handover_protocols.create_handover_protocol(self._make_payload(protocol_type="move_out"))
        assert len(_list_handover_protocols(protocol_type="move_in")) == 1
        assert len(_list_handover_protocols(protocol_type="move_out")) == 1

    def test_get(self) -> None:
        hp = handover_protocols.create_handover_protocol(self._make_payload())
        fetched = handover_protocols.get_handover_protocol(hp.id)
        assert fetched.id == hp.id

    def test_get_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            handover_protocols.get_handover_protocol("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update(self) -> None:
        hp = handover_protocols.create_handover_protocol(self._make_payload())
        updated = handover_protocols.update_handover_protocol(
            hp.id, self._make_payload(overall_condition="good"),
        )
        assert updated.overall_condition == "good"
        assert updated.id == hp.id

    def test_update_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            handover_protocols.update_handover_protocol("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_patch(self) -> None:
        hp = handover_protocols.create_handover_protocol(self._make_payload())
        patched = handover_protocols.patch_handover_protocol(
            hp.id, HandoverProtocolPatch(status="signed"),
        )
        assert patched.status == "signed"
        assert patched.protocol_type == "move_in"  # unchanged

    def test_patch_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            handover_protocols.patch_handover_protocol("nonexistent", HandoverProtocolPatch(status="signed"))
        assert exc_info.value.status_code == 404

    def test_delete(self) -> None:
        hp = handover_protocols.create_handover_protocol(self._make_payload())
        handover_protocols.delete_handover_protocol(hp.id)
        assert _list_handover_protocols() == []

    def test_delete_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            handover_protocols.delete_handover_protocol("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_invalid_contract(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            handover_protocols.create_handover_protocol(self._make_payload(contract_id="bad"))
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Meter Readings (sub-resource of handover protocols)
# ---------------------------------------------------------------------------

class TestMeterReadings:
    def setup_method(self) -> None:
        _clear_store()
        self.prop_id, self.unit_id, self.tenant_id, self.contract_id = _create_contract_chain()
        hp = store.create_handover_protocol(
            HandoverProtocolCreate(
                contract_id=self.contract_id,
                unit_id=self.unit_id,
                protocol_type="move_in",
                protocol_date=date(2024, 1, 15),
            ),
        )
        self.protocol_id = hp.id

    def _make_reading(self, **overrides):
        defaults = dict(
            handover_id=self.protocol_id,
            meter_type="electricity",
            reading_value=12345.0,
            unit="kWh",
        )
        defaults.update(overrides)
        return MeterReadingCreate(**defaults)

    def test_create_meter_reading(self) -> None:
        mr = handover_protocols.create_meter_reading(self.protocol_id, self._make_reading())
        assert mr.handover_id == self.protocol_id
        assert mr.reading_value == 12345.0
        assert mr.id

    def test_get_meter_reading(self) -> None:
        mr = handover_protocols.create_meter_reading(self.protocol_id, self._make_reading())
        fetched = handover_protocols.get_meter_reading(self.protocol_id, mr.id)
        assert fetched.id == mr.id

    def test_get_meter_reading_wrong_protocol(self) -> None:
        mr = handover_protocols.create_meter_reading(self.protocol_id, self._make_reading())
        with pytest.raises(HTTPException) as exc_info:
            handover_protocols.get_meter_reading("wrong-protocol", mr.id)
        assert exc_info.value.status_code == 404

    def test_delete_meter_reading(self) -> None:
        mr = handover_protocols.create_meter_reading(self.protocol_id, self._make_reading())
        handover_protocols.delete_meter_reading(self.protocol_id, mr.id)
        assert _list_meter_readings() == []

    def test_delete_meter_reading_wrong_protocol(self) -> None:
        mr = handover_protocols.create_meter_reading(self.protocol_id, self._make_reading())
        with pytest.raises(HTTPException) as exc_info:
            handover_protocols.delete_meter_reading("wrong-protocol", mr.id)
        assert exc_info.value.status_code == 404

    def test_list_all_meter_readings(self) -> None:
        handover_protocols.create_meter_reading(self.protocol_id, self._make_reading(meter_type="electricity"))
        handover_protocols.create_meter_reading(self.protocol_id, self._make_reading(meter_type="gas"))
        assert len(_list_meter_readings()) == 2

    def test_list_meter_readings_filter_handover_id(self) -> None:
        handover_protocols.create_meter_reading(self.protocol_id, self._make_reading())
        assert len(_list_meter_readings(handover_id=self.protocol_id)) == 1
        assert len(_list_meter_readings(handover_id="other")) == 0

    def test_list_meter_readings_filter_meter_type(self) -> None:
        handover_protocols.create_meter_reading(self.protocol_id, self._make_reading(meter_type="electricity"))
        handover_protocols.create_meter_reading(self.protocol_id, self._make_reading(meter_type="water"))
        assert len(_list_meter_readings(meter_type="electricity")) == 1
        assert len(_list_meter_readings(meter_type="water")) == 1


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

class TestBudgets:
    def setup_method(self) -> None:
        _clear_store()
        self.prop_id, self.unit_id, self.tenant_id, self.contract_id = _create_contract_chain()

    def _make_payload(self, **overrides):
        defaults = dict(
            property_id=self.prop_id,
            year=2024,
            category="maintenance",
            planned_amount=10000.0,
            actual_amount=0.0,
        )
        defaults.update(overrides)
        return BudgetCreate(**defaults)

    def test_list_empty(self) -> None:
        assert _list_budgets() == []

    def test_create(self) -> None:
        b = budgets.create_budget(self._make_payload())
        assert b.property_id == self.prop_id
        assert b.planned_amount == 10000.0
        assert b.id

    def test_list_returns_created(self) -> None:
        budgets.create_budget(self._make_payload())
        budgets.create_budget(self._make_payload(category="renovation"))
        assert len(_list_budgets()) == 2

    def test_list_filter_property_id(self) -> None:
        budgets.create_budget(self._make_payload())
        assert len(_list_budgets(property_id=self.prop_id)) == 1
        assert len(_list_budgets(property_id="other")) == 0

    def test_list_filter_year(self) -> None:
        budgets.create_budget(self._make_payload(year=2024))
        budgets.create_budget(self._make_payload(year=2025))
        assert len(_list_budgets(year=2024)) == 1
        assert len(_list_budgets(year=2025)) == 1

    def test_list_filter_category(self) -> None:
        budgets.create_budget(self._make_payload(category="maintenance"))
        budgets.create_budget(self._make_payload(category="renovation"))
        assert len(_list_budgets(category="maintenance")) == 1
        assert len(_list_budgets(category="other")) == 0

    def test_get(self) -> None:
        b = budgets.create_budget(self._make_payload())
        fetched = budgets.get_budget(b.id)
        assert fetched.id == b.id

    def test_get_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            budgets.get_budget("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update(self) -> None:
        b = budgets.create_budget(self._make_payload())
        updated = budgets.update_budget(b.id, self._make_payload(planned_amount=20000.0))
        assert updated.planned_amount == 20000.0
        assert updated.id == b.id

    def test_update_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            budgets.update_budget("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_patch(self) -> None:
        b = budgets.create_budget(self._make_payload())
        patched = budgets.patch_budget(b.id, BudgetPatch(actual_amount=5000.0))
        assert patched.actual_amount == 5000.0
        assert patched.planned_amount == 10000.0  # unchanged

    def test_patch_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            budgets.patch_budget("nonexistent", BudgetPatch(actual_amount=100.0))
        assert exc_info.value.status_code == 404

    def test_delete(self) -> None:
        b = budgets.create_budget(self._make_payload())
        budgets.delete_budget(b.id)
        assert _list_budgets() == []

    def test_delete_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            budgets.delete_budget("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_invalid_property(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            budgets.create_budget(self._make_payload(property_id="bad"))
        assert exc_info.value.status_code == 400

    def test_budget_analysis_empty(self) -> None:
        result = budgets.budget_analysis(property_id=None, year=None)
        assert result["total_planned"] == 0
        assert result["total_actual"] == 0
        assert result["total_deviation"] == 0
        assert result["utilization_percent"] == 0
        assert result["by_category"] == []

    def test_budget_analysis_with_data(self) -> None:
        budgets.create_budget(self._make_payload(
            category="maintenance", planned_amount=10000.0, actual_amount=8000.0,
        ))
        budgets.create_budget(self._make_payload(
            category="renovation", planned_amount=5000.0, actual_amount=6000.0,
        ))
        result = budgets.budget_analysis(property_id=None, year=None)
        assert result["total_planned"] == 15000.0
        assert result["total_actual"] == 14000.0
        assert result["total_deviation"] == -1000.0
        assert len(result["by_category"]) == 2

    def test_budget_analysis_filter_property(self) -> None:
        budgets.create_budget(self._make_payload(planned_amount=10000.0, actual_amount=5000.0))
        result = budgets.budget_analysis(property_id=self.prop_id, year=None)
        assert result["total_planned"] == 10000.0
        result_other = budgets.budget_analysis(property_id="other", year=None)
        assert result_other["total_planned"] == 0

    def test_budget_analysis_filter_year(self) -> None:
        budgets.create_budget(self._make_payload(year=2024, planned_amount=10000.0, actual_amount=5000.0))
        budgets.create_budget(self._make_payload(year=2025, planned_amount=20000.0, actual_amount=15000.0))
        result_2024 = budgets.budget_analysis(property_id=None, year=2024)
        assert result_2024["total_planned"] == 10000.0
        result_2025 = budgets.budget_analysis(property_id=None, year=2025)
        assert result_2025["total_planned"] == 20000.0

    def test_budget_analysis_utilization_percent(self) -> None:
        budgets.create_budget(self._make_payload(planned_amount=10000.0, actual_amount=5000.0))
        result = budgets.budget_analysis(property_id=None, year=None)
        assert result["utilization_percent"] == 50.0


# ---------------------------------------------------------------------------
# Escalation Rules
# ---------------------------------------------------------------------------

class TestEscalation:
    def setup_method(self) -> None:
        _clear_store()

    def _make_rule(self, **overrides):
        defaults = dict(
            name="Overdue Task Rule",
            entity_type="task",
            condition_field="due_date",
            days_overdue=7,
            action="notify",
            notification_severity="warning",
            is_active=True,
        )
        defaults.update(overrides)
        return EscalationRuleCreate(**defaults)

    def test_list_empty(self) -> None:
        assert _list_rules() == []

    def test_create(self) -> None:
        rule = escalation.create_rule(self._make_rule())
        assert rule.name == "Overdue Task Rule"
        assert rule.entity_type == "task"
        assert rule.id

    def test_list_returns_created(self) -> None:
        escalation.create_rule(self._make_rule())
        escalation.create_rule(self._make_rule(name="Rule2", entity_type="maintenance"))
        assert len(_list_rules()) == 2

    def test_list_filter_entity_type(self) -> None:
        escalation.create_rule(self._make_rule(entity_type="task"))
        escalation.create_rule(self._make_rule(entity_type="maintenance"))
        assert len(_list_rules(entity_type="task")) == 1
        assert len(_list_rules(entity_type="maintenance")) == 1

    def test_list_filter_is_active(self) -> None:
        escalation.create_rule(self._make_rule(is_active=True))
        escalation.create_rule(self._make_rule(is_active=False, name="Inactive"))
        assert len(_list_rules(is_active=True)) == 1
        assert len(_list_rules(is_active=False)) == 1

    def test_get(self) -> None:
        rule = escalation.create_rule(self._make_rule())
        fetched = escalation.get_rule(rule.id)
        assert fetched.id == rule.id

    def test_get_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            escalation.get_rule("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update(self) -> None:
        rule = escalation.create_rule(self._make_rule())
        updated = escalation.update_rule(rule.id, self._make_rule(name="Updated Rule"))
        assert updated.name == "Updated Rule"
        assert updated.id == rule.id

    def test_update_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            escalation.update_rule("nonexistent", self._make_rule())
        assert exc_info.value.status_code == 404

    def test_patch(self) -> None:
        rule = escalation.create_rule(self._make_rule())
        patched = escalation.patch_rule(rule.id, EscalationRulePatch(days_overdue=14))
        assert patched.days_overdue == 14
        assert patched.name == "Overdue Task Rule"  # unchanged

    def test_patch_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            escalation.patch_rule("nonexistent", EscalationRulePatch(name="X"))
        assert exc_info.value.status_code == 404

    def test_delete(self) -> None:
        rule = escalation.create_rule(self._make_rule())
        escalation.delete_rule(rule.id)
        assert _list_rules() == []

    def test_delete_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            escalation.delete_rule("nonexistent")
        assert exc_info.value.status_code == 404

    def test_run_escalation_no_rules(self) -> None:
        result = escalation.run_escalation(as_of=date(2024, 3, 1))
        assert result["rules_checked"] == 0
        assert result["notifications_generated"] == 0

    def test_run_escalation_task_overdue(self) -> None:
        """An active rule + overdue task should produce a notification."""
        prop_id, unit_id, _, _ = _create_contract_chain()
        store.create_task(TaskCreate(
            title="Fix roof",
            property_id=prop_id,
            due_date=date(2024, 1, 1),
            status="open",
        ))
        escalation.create_rule(self._make_rule(
            entity_type="task", days_overdue=7,
        ))
        result = escalation.run_escalation(as_of=date(2024, 2, 1))
        assert result["rules_checked"] == 1
        assert result["notifications_generated"] == 1
        assert len(result["notification_ids"]) == 1

    def test_run_escalation_inactive_rule_skipped(self) -> None:
        """Inactive rules should not be processed."""
        prop_id, _, _, _ = _create_contract_chain()
        store.create_task(TaskCreate(
            title="Fix door",
            property_id=prop_id,
            due_date=date(2024, 1, 1),
            status="open",
        ))
        escalation.create_rule(self._make_rule(is_active=False))
        result = escalation.run_escalation(as_of=date(2024, 2, 1))
        assert result["rules_checked"] == 0
        assert result["notifications_generated"] == 0

    def test_run_escalation_task_not_overdue_enough(self) -> None:
        """Task due_date within the days_overdue window should not trigger."""
        prop_id, _, _, _ = _create_contract_chain()
        store.create_task(TaskCreate(
            title="Paint wall",
            property_id=prop_id,
            due_date=date(2024, 1, 25),
            status="open",
        ))
        escalation.create_rule(self._make_rule(
            entity_type="task", days_overdue=7,
        ))
        # as_of is 2024-01-28 = only 3 days overdue, rule requires 7
        result = escalation.run_escalation(as_of=date(2024, 1, 28))
        assert result["notifications_generated"] == 0


# ---------------------------------------------------------------------------
# Change History
# ---------------------------------------------------------------------------

class TestHistory:
    def setup_method(self) -> None:
        _clear_store()

    def test_list_empty(self) -> None:
        assert _list_history() == []

    def test_list_returns_entries(self) -> None:
        store.add_change_history(
            entity_type="property", entity_id="p1",
            field_name="name", old_value="Old", new_value="New",
        )
        store.add_change_history(
            entity_type="unit", entity_id="u1",
            field_name="label", old_value="A", new_value="B",
        )
        assert len(_list_history()) == 2

    def test_list_filter_entity_type(self) -> None:
        store.add_change_history(
            entity_type="property", entity_id="p1",
            field_name="name", old_value="Old", new_value="New",
        )
        store.add_change_history(
            entity_type="unit", entity_id="u1",
            field_name="label", old_value="A", new_value="B",
        )
        assert len(_list_history(entity_type="property")) == 1
        assert len(_list_history(entity_type="unit")) == 1
        assert len(_list_history(entity_type="contract")) == 0

    def test_list_filter_entity_id(self) -> None:
        store.add_change_history(
            entity_type="property", entity_id="p1",
            field_name="name", old_value="Old", new_value="New",
        )
        store.add_change_history(
            entity_type="property", entity_id="p2",
            field_name="name", old_value="X", new_value="Y",
        )
        assert len(_list_history(entity_id="p1")) == 1
        assert len(_list_history(entity_id="p2")) == 1

    def test_list_sorted_descending(self) -> None:
        e1 = store.add_change_history(
            entity_type="property", entity_id="p1",
            field_name="name", old_value="Old", new_value="New",
        )
        e2 = store.add_change_history(
            entity_type="property", entity_id="p1",
            field_name="status", old_value="active", new_value="archived",
        )
        result = _list_history()
        # Most recent first (e2 was added after e1)
        assert result[0].id == e2.id
        assert result[1].id == e1.id

    def test_list_pagination(self) -> None:
        for i in range(5):
            store.add_change_history(
                entity_type="property", entity_id=f"p{i}",
                field_name="name", old_value=f"old{i}", new_value=f"new{i}",
            )
        assert len(_list_history(skip=0, limit=2)) == 2
        assert len(_list_history(skip=3, limit=10)) == 2
        assert len(_list_history(skip=10, limit=10)) == 0

    def test_get_entity_history(self) -> None:
        store.add_change_history(
            entity_type="property", entity_id="p1",
            field_name="name", old_value="Old", new_value="New",
        )
        store.add_change_history(
            entity_type="property", entity_id="p1",
            field_name="address", old_value="Str1", new_value="Str2",
        )
        store.add_change_history(
            entity_type="unit", entity_id="u1",
            field_name="label", old_value="A", new_value="B",
        )
        result = history.get_entity_history("property", "p1")
        assert len(result) == 2
        assert all(h.entity_type == "property" and h.entity_id == "p1" for h in result)

    def test_get_entity_history_empty(self) -> None:
        result = history.get_entity_history("contract", "nonexistent")
        assert result == []

    def test_history_entry_fields(self) -> None:
        entry = store.add_change_history(
            entity_type="tenant", entity_id="t1",
            field_name="full_name", old_value="Max", new_value="Moritz",
            changed_by="admin", reason="Name correction",
        )
        assert entry.entity_type == "tenant"
        assert entry.entity_id == "t1"
        assert entry.field_name == "full_name"
        assert entry.old_value == "Max"
        assert entry.new_value == "Moritz"
        assert entry.changed_by == "admin"
        assert entry.reason == "Name correction"
        assert entry.changed_at is not None
