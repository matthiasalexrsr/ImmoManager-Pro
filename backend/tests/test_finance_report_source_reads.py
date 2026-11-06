"""Source DTO reuse remains local to one authorized, unchanged report snapshot."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.finance_models import ReportDefinition
from backend.models import (
    AccountCreate,
    Booking,
    BookingCreate,
    InvoiceCreate,
    PortfolioCreate,
    PropertyCreate,
    UnitCreate,
    UtilityStatement,
)
from backend.services import finance_reports, report_provenance
from backend.services.finance_ledger import FinanceFilter, booking_sources
from backend.services.maintenance_rows import Rows
from backend.services.portfolio_scope import AccessScope, scope_context, scope_from_user
from backend.services.receivable_residuals import digest
from backend.tests.test_finance_packages_v2 import clean as clean
from backend.tests.test_finance_packages_v2 import estate as estate


def booking(estate, amount=12.34):
    return store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2026, 1, 10), amount=amount))


def payload(*identifiers):
    return {"definition": {"as_of": "2026-01-31"},
        "sources": [{"identity": "booking:" + identifier, "amount": "12.34"} for identifier in identifiers]}


@pytest.mark.parametrize("kind", ["cash-v2", "performance-period-v2", "liquidity-v2"])
def test_local_source_reuse_preserves_all_numbers_definitions_and_provenance(estate, monkeypatch, kind):
    booking(estate)
    store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Prüfbetrieb",
        invoice_date=date(2026, 1, 10), due_date=date(2026, 2, 1), net_amount=10, gross_amount=11.90))
    definition = ReportDefinition.model_validate({"kind": kind, "as_of": "2026-01-15",
        "rent_collection_percent": 80, "arrears_collection_percent": 20})
    actual = finance_reports.compute(store, definition)
    original = report_provenance.enrich

    def uncached(source, result, mode, **kwargs):
        return original(source, result, mode)

    monkeypatch.setattr(report_provenance, "enrich", uncached)
    expected = finance_reports.compute(store, definition)
    actual.pop("generated_at")
    expected.pop("generated_at")
    assert actual == expected
    assert actual["result_hash"] == expected["result_hash"]
    assert actual["provenance"]["source_records"] > 0


def test_cached_and_missing_source_ids_are_combined_without_reloading_known_rows(estate, monkeypatch):
    first = booking(estate)
    second = booking(estate, 56.78)
    known = report_provenance.SourceRecords(store)
    known.remember("bookings", [first])
    original = Rows.find
    reads = []

    def find(self, table, **criteria):
        if table == "bookings":
            reads.append(set(criteria["id"]))
        return original(self, table, **criteria)

    monkeypatch.setattr(Rows, "find", find)
    result = payload(first.id, second.id)
    report_provenance.enrich(store, result, "test", known_records=known)
    assert reads == [{second.id}]
    assert [item["provenance"]["source_sha256"] for item in result["sources"]] == [
        digest(first.model_dump(mode="json")), digest(second.model_dump(mode="json"))]


@pytest.mark.parametrize("corruption", ["changed_fields", "wrong_id", "wrong_type", "missing_fields", "bad_stamp", "plain_mapping"])
def test_invalid_entries_fall_back_to_authorized_source_read(estate, monkeypatch, corruption):
    original = booking(estate)
    candidate = original.model_copy(deep=True)
    known = report_provenance.SourceRecords(store)
    known.remember("bookings", [candidate])
    if corruption == "changed_fields":
        candidate.amount = 999999.0
    elif corruption == "wrong_id":
        candidate.id = "unrelated-id"
    elif corruption == "wrong_type":
        known._records["bookings"][original.id] = (SimpleNamespace(**candidate.__dict__), candidate.__dict__.copy())
    elif corruption == "missing_fields":
        known._records["bookings"][original.id] = (Booking.model_construct(id=original.id), {"id": original.id})
    elif corruption == "bad_stamp":
        monkeypatch.setitem(known._records["bookings"], original.id, ("invalid",))
    original_find = Rows.find
    reads = []

    def find(self, table, **criteria):
        if table == "bookings":
            reads.append(set(criteria["id"]))
        return original_find(self, table, **criteria)

    monkeypatch.setattr(Rows, "find", find)
    result = payload(original.id)
    report_provenance.enrich(store, result, "test",
        known_records={"bookings": {original.id: candidate}} if corruption == "plain_mapping" else known)
    assert reads == [{original.id}]
    assert result["sources"][0]["provenance"]["source_sha256"] == digest(original.model_dump(mode="json"))


def test_incomplete_model_cannot_be_collected_as_authoritative_source(estate):
    original = booking(estate)
    known = report_provenance.SourceRecords(store)
    known.remember("bookings", [Booking.model_construct(id=original.id)])
    assert known.selected(store, "bookings", {original.id}) == {}


@pytest.mark.parametrize("field", ["final_document", "line_items"])
def test_mutable_statement_evidence_still_has_an_independent_field_snapshot(estate, field):
    statement = UtilityStatement(id="nested-evidence", billing_period_id="period", unit_id=estate[2].id,
        total_cost=12, advance_paid=0, balance=12,
        final_document={"rows": [{"amount": "12.00"}]}, line_items=[{"allocated_amount": 12.0}])
    known = report_provenance.SourceRecords(store)
    known.remember("utility_statements", [statement])
    assert known.selected(store, "utility_statements", {statement.id}) == {statement.id: statement}
    value = getattr(statement, field)
    if field == "final_document":
        value["rows"][0]["amount"] = "999.00"
    else:
        value[0]["allocated_amount"] = 999.0
    assert known.selected(store, "utility_statements", {statement.id}) == {}


def test_collector_is_bound_to_exact_snapshot_store(estate):
    original = booking(estate)
    known = report_provenance.SourceRecords(store)
    known.remember("bookings", [original])
    assert known.selected(object(), "bookings", {original.id}) == {}
    assert known.selected(store, "bookings", {original.id}) == {original.id: original}


def test_prior_unrestricted_source_cannot_escape_a_new_restricted_scope(estate):
    original = booking(estate)
    known = report_provenance.SourceRecords(store)
    known.remember("bookings", [original])
    foreign = store.create_portfolio(PortfolioCreate(name="Andere Grenze"))
    store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Anderes Haus", property_type="residential"))
    restricted = AccessScope("report-reader", "readonly", False, (foreign.id,))
    with scope_context(restricted):
        assert known.selected(store, "bookings", {original.id}) == {}
        with pytest.raises(HTTPException) as failure:
            report_provenance.enrich(store, payload(original.id), "test", known_records=known)
    assert failure.value.status_code == 409


def test_same_store_new_report_does_not_reuse_old_models(estate):
    original = booking(estate)
    before = finance_reports.compute(store, ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31)))
    store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2026, 1, 11), amount=1.23))
    after = finance_reports.compute(store, ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31)))
    assert after["totals"]["net"] == "13.57"
    assert after["result_hash"] != before["result_hash"]
    assert original.id in {item["identity"].split(":")[1] for item in after["sources"]}


def test_cash_source_rows_are_read_once_per_calculation(estate, monkeypatch):
    booking(estate)
    original = finance_reports.booking_sources
    calls = []

    def sources(source, definition):
        calls.append(definition)
        return original(source, definition)

    monkeypatch.setattr(finance_reports, "booking_sources", sources)
    result = finance_reports.compute(store, ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31)))
    assert result["totals"]["net"] == "12.34"
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["cash-v2", "performance-period-v2", "liquidity-v2"])
@pytest.mark.parametrize("entrypoint", ["get", "post", "saved"])
def test_json_report_http_bytes_stay_identical_without_recursive_reencoding(estate, monkeypatch, kind, entrypoint):
    import fastapi.routing

    store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2026, 1, 10), amount=12.34, payment_text="Miete für Käthe – Prüfung"))
    owner = auth.register_user("owner", "owner@example.test", "Owner", "Secret123", "eigentuemer", portfolio_access="all")
    monkeypatch.setattr(finance_reports, "retrieval_time", lambda: datetime(2026, 11, 6, 12, tzinfo=timezone.utc))
    definition = ReportDefinition.model_validate({"kind": kind, "as_of": "2026-01-15"})
    expected = finance_reports.compute(store, definition)
    baseline_bytes = JSONResponse(jsonable_encoder(expected)).body
    original_encoder = fastapi.routing.jsonable_encoder

    def encoder(obj, *values, **named):
        if isinstance(obj, dict) and "definition_hash" in obj and "result_hash" in obj:
            pytest.fail("JSON-ready report must not traverse FastAPI's generic encoder again")
        return original_encoder(obj, *values, **named)

    monkeypatch.setattr(fastapi.routing, "jsonable_encoder", encoder)
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)}) as client:
        if entrypoint == "saved":
            saved = client.post("/api/v1/reports/v2/saved", json={"name": "Prüfstand", "definition": definition.model_dump(mode="json"),
                "idempotency_key": "report-http-" + kind})
            assert saved.status_code == 200, saved.text
            response = client.get("/api/v1/reports/v2/saved/" + saved.json()["id"])
        elif entrypoint == "post":
            response = client.post("/api/v1/reports/v2/preview", json=definition.model_dump(mode="json"),
                params={"expected_result_hash": expected["result_hash"]})
        else:
            response = client.get("/api/v1/reports/v2/preview", params={"definition": definition.model_dump_json(),
                "expected_result_hash": expected["result_hash"]})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    assert response.content == baseline_bytes


@pytest.mark.parametrize("method", ["get", "post"])
def test_json_preview_keeps_the_stale_result_hash_guard(estate, method):
    booking(estate)
    definition = ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31))
    before = finance_reports.compute(store, definition)
    booking(estate, 56.78)
    owner = auth.register_user("owner", "owner@example.test", "Owner", "Secret123", "eigentuemer", portfolio_access="all")
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)}) as client:
        if method == "post":
            response = client.post("/api/v1/reports/v2/preview", json=definition.model_dump(mode="json"),
                params={"expected_result_hash": before["result_hash"]})
        else:
            response = client.get("/api/v1/reports/v2/preview", params={"definition": definition.model_dump_json(),
                "expected_result_hash": before["result_hash"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert "Berichtsquellen" in response.json()["error"]["message"]


@pytest.mark.parametrize("selection", ["all", "portfolio", "property", "unit"])
@pytest.mark.parametrize("restricted", [False, True])
def test_forecast_opening_uses_the_same_ordered_scoped_cash_sources(estate, monkeypatch, selection, restricted):
    other_portfolio = store.create_portfolio(PortfolioCreate(name="Getrennter Bestand"))
    other_property = store.create_property(PropertyCreate(portfolio_id=other_portfolio.id,
        name="Getrenntes Haus", property_type="residential"))
    other_unit = store.create_unit(UnitCreate(property_id=other_property.id, label="Andere Einheit", unit_type="residential"))
    other_account = store.create_account(AccountCreate(portfolio_id=other_portfolio.id, name="Andere Bank", account_type="bank"))
    for account_id, property_id, unit_id, day, amount in (
        (estate[5].id, estate[1].id, estate[2].id, 10, 12.34),
        (estate[5].id, None, estate[2].id, 10, -1.23),
        (estate[5].id, None, None, 11, 2.0),
        (other_account.id, other_property.id, other_unit.id, 10, 99.0),
        (estate[5].id, estate[1].id, estate[2].id, 16, 123.0),
    ):
        store.create_booking(BookingCreate(account_id=account_id, property_id=property_id,
            unit_id=unit_id, booking_date=date(2026, 1, day), amount=amount))
    filters = {"all": {}, "portfolio": {"portfolio_id": estate[0].id},
        "property": {"property_id": estate[1].id}, "unit": {"unit_id": estate[2].id}}[selection]
    scope = None
    if restricted:
        auth.register_user("owner", "owner@example.test", "Owner", "Secret123", "eigentuemer", portfolio_access="all")
        reader = auth.register_user("scoped-report", "reader@example.test", "Lesekonto", "Secret123", "readonly",
            portfolio_access="selected", portfolio_ids=[estate[0].id])
        stored_reader = auth.get_user_by_id(reader.id)
        assert stored_reader is not None
        scope = scope_from_user(stored_reader)
    with scope_context(scope):
        expected = booking_sources(store, FinanceFilter(date_to=date(2026, 1, 15), **filters))
        calls = []
        original = finance_reports.booking_sources

        def sources(source, definition):
            calls.append(definition)
            return original(source, definition)

        monkeypatch.setattr(finance_reports, "booking_sources", sources)
        result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15), **filters))
    opening = [item for item in result["opening_sources"] if item["identity"].startswith("booking:")]
    assert [item["identity"] for item in opening] == ["booking:" + row.id for row in expected]
    assert [item["amount"] for item in opening] == [f"{row.amount:.2f}" for row in expected]
    assert len(calls) == (0 if selection == "all" else 1)

