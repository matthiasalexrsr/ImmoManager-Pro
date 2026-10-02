"""Actual persisted cash, invalid legacy amounts, coherent snapshots and scopes."""

from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from backend import auth, dependencies
from backend.db.orm_models import Base
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import accounts as router
from backend.services import account_balances as balance
from backend.services.concurrency import ConcurrencyMiddleware, etag
from backend.services.payments import PaymentCreate, PaymentReversalCreate
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.storage import InMemoryStore
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401


@pytest.fixture(params=["memory", "sql"])
def ledger(request, tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "balances.sqlite").as_posix(), hide_parameters=True)
    with engine.connect() as db:
        db.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    db = Session(engine)
    store = InMemoryStore() if request.param == "memory" else SQLAlchemyStore(db)
    factory = sessionmaker(engine)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore() if request.param == "memory" else auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", None if request.param == "memory" else factory)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    monkeypatch.setattr(router, "store", store)
    monkeypatch.setattr(dependencies, "store", store)
    with scope_context(None):
        portfolios = [store.create_portfolio(PortfolioCreate(name="Synthetic " + str(index))) for index in range(2)]
        accounts = [store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Bank " + str(index), account_type="bank",
            opening_balance=100.05, balance=98)) for index, portfolio in enumerate(portfolios)]
        owner = auth.register_user("owner", "owner@example.test", "Synthetic", "Synthetic passphrase123!", "eigentuemer")
        member = auth.register_user("member", "member@example.test", "Synthetic", "Synthetic passphrase123!", "buchhaltung",
            portfolio_access="selected", portfolio_ids=[portfolios[0].id])
    app = FastAPI()
    app.add_middleware(ConcurrencyMiddleware)
    app.include_router(router.router, prefix="/api/v1")
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        yield store, accounts, portfolios, client, owner, member, engine
    db.close()
    engine.dispose()


def booking(store, account, amount, *, status="open", day=1, identifier=None):
    value = store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 1, day), amount=amount,
        status=status, payment_text="Synthetic cash"))
    if identifier and not hasattr(store, "db"):
        raw = object.__getattribute__(store, "__dict__")["bookings"]
        raw.pop(value.id)
        value = value.model_copy(update={"id": identifier})
        raw[identifier] = value
    return value


def headers(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id)}


@pytest.mark.parametrize("raw, expected", [(0, 0), ("0.10", 10), ("-0.20", -20), ("1.2300", 123), ("1E+5", 10000000), ("0E-99999", 0)])
def test_exact_cent_assembly(raw, expected):
    assert balance.cents(raw) == expected


@pytest.mark.parametrize("raw, code", [(None, "amount_invalid"), (True, "amount_invalid"), ("bad", "amount_invalid"),
    ("nan", "amount_not_finite"), ("-Infinity", "amount_not_finite"), ("0.001", "amount_fractional_cent"),
    ("1.000000000000000000000000000000001", "amount_fractional_cent"), ("1e-999999", "amount_fractional_cent"),
    ("1e+999999", "amount_capacity")])
def test_bad_money_does_not_round_or_overflow(raw, code):
    with pytest.raises(ValueError, match=code):
        balance.cents(raw)


def test_status_is_classification_every_stored_cash_row_counts_once_and_no_global_preload(ledger, monkeypatch):
    store, accounts, _, _, *_ = ledger
    for amount, status in ((.1, "open"), (.2, "matched"), (-.3, "booked"), (1.01, "confirmed"), (-2.02, "legacy-cancelled")):
        booking(store, accounts[0], amount, status=status)
    booking(store, accounts[1], 999)
    monkeypatch.setattr(store, "list_bookings", lambda: pytest.fail("A balance must not preload the global booking list"))
    value = balance.account_balance(store, accounts[0].id)
    assert (value["opening_balance_cents"], value["bookings_sum_cents"], value["calculated_balance_cents"], value["difference_cents"]) == ("10005", "-101", "9904", "104")
    assert value["income_sum_cents"] == "131" and value["expense_sum_cents"] == "-232"
    assert value["booking_count"] == 5 and value["issues_count"] == 0
    assert list(value["status_totals"]) == list(balance.STATUSES)
    assert value["status_totals"]["other"] == {"booking_count": 1, "amount_cents": "-202", "invalid_count": 0}
    assert value["opening_is_undated"] and value["comparison_is_undated"]
    assert store.get_account(accounts[0].id).balance == 98


def test_inclusive_as_of_with_undated_opening_and_undated_comparison_is_explicit(ledger):
    store, accounts, *_ = ledger
    booking(store, accounts[0], .01, day=1)
    booking(store, accounts[0], .02, day=2)
    booking(store, accounts[0], .03, day=3)
    value = balance.account_balance(store, accounts[0].id, as_of=date(2026, 1, 2))
    assert value["bookings_sum_cents"] == "3" and value["calculated_balance_cents"] == "10008"
    assert value["booking_count"] == 2 and value["first_booking_date"] == "2026-01-01" and value["last_booking_date"] == "2026-01-02"
    assert value["as_of"] == "2026-01-02" and value["comparison_is_undated"]


def corrupt(store, account, value, field="amount", item=None):
    if hasattr(store, "db"):
        table, column = ("bookings", "amount") if field == "amount" else ("accounts", "balance" if field == "comparison_balance" else field)
        store.db.execute(text(f"UPDATE {table} SET {column}=:value WHERE id=:id"), {"value": value, "id": item.id if table == "bookings" else account.id})
        store.db.commit()
    else:
        raw = object.__getattribute__(store, "__dict__")
        if field == "amount":
            raw["bookings"][item.id] = item.model_copy(update={"amount": value})
        else:
            raw["accounts"][account.id] = raw["accounts"][account.id].model_copy(update={"balance" if field == "comparison_balance" else field: value})


@pytest.mark.parametrize("field", ["opening_balance", "comparison_balance", "amount"])
def test_legacy_fractional_cents_are_visible_not_rounded_and_no_false_projection(ledger, field):
    store, accounts, _, client, owner, *_ = ledger
    item = booking(store, accounts[0], .01)
    corrupt(store, accounts[0], 1.001, field, item)
    response = client.get(f"/api/v1/accounts/{accounts[0].id}/balance-summary", headers=headers(owner))
    assert response.status_code == 200
    value = response.json()
    assert value["issues_count"] == 1 and value["issues_sample"][0]["code"] == "amount_fractional_cent"
    assert value["issues_sample"][0]["field"] == field
    assert value["difference_cents"] is None
    assert value["is_computable"] == (field == "comparison_balance")
    assert value["calculated_balance_cents"] == ("10006" if field == "comparison_balance" else None)
    assert response.headers["cache-control"] == "no-store"


def test_all_invalid_sources_are_reachable_on_bound_source_pages_and_changes_require_reload(ledger, monkeypatch):
    store, accounts, *_ = ledger
    monkeypatch.setattr(balance, "BATCH_SIZE", 3)
    for index in range(27):
        item = booking(store, accounts[0], .01, identifier="row-" + str(index).zfill(2))
        corrupt(store, accounts[0], 1.001, item=item)
    summary = balance.account_balance(store, accounts[0].id)
    assert summary["issues_count"] == 27 and len(summary["issues_sample"]) == 20 and summary["issues_next_cursor"]
    all_ids = []
    cursor = None
    while True:
        page = balance.account_balance(store, accounts[0].id, kind="issues", cursor=cursor, source_hash=summary["source_hash"], page_size=4)
        all_ids.extend(item["source_id"] for item in page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(set(all_ids)) == 27
    late_page = balance.account_balance(store, accounts[0].id, kind="issues", cursor=summary["issues_next_cursor"])
    assert len(late_page["items"]) == 7
    booking(store, accounts[0], 2)
    with pytest.raises(balance.BalanceError, match="Quellen wurden geändert"):
        balance.account_balance(store, accounts[0].id, kind="issues", source_hash=summary["source_hash"])


def test_direct_ids_source_pages_and_cross_references_are_server_scoped(ledger):
    store, accounts, portfolios, client, owner, member, _ = ledger
    booking(store, accounts[0], .01)
    for suffix in ("balance-summary", "balance-sources"):
        assert client.get(f"/api/v1/accounts/{accounts[0].id}/{suffix}").status_code == 401
        denied = client.get(f"/api/v1/accounts/{accounts[1].id}/{suffix}", headers=headers(member))
        assert denied.status_code == 404 and accounts[1].name not in denied.text
    assert client.get(f"/api/v1/accounts/{accounts[0].id}/balance-summary", headers=headers(member)).status_code == 200
    with scope_context(None):
        foreign = store.create_property(PropertyCreate(portfolio_id=portfolios[1].id, name="Hidden source", property_type="residential"))
        store.create_booking(BookingCreate(account_id=accounts[0].id, property_id=foreign.id, booking_date=date(2026, 1, 2), amount=1234))
    denied = client.get(f"/api/v1/accounts/{accounts[0].id}/balance-summary", headers=headers(member))
    assert denied.status_code == 403 and foreign.id not in denied.text and "1234" not in denied.text
    assert client.get(f"/api/v1/accounts/{accounts[0].id}/balance-summary", headers=headers(owner)).json()["booking_count"] == 2


def test_late_grant_change_returns_no_old_projection_or_source_rows(ledger, monkeypatch):
    store, accounts, _, client, owner, member, _ = ledger
    booking(store, accounts[0], .01)
    original = balance.refresh_scope
    calls = 0
    def fresh(scope):
        nonlocal calls
        calls += 1
        if calls == 2:
            auth.update_user(member.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=owner.id)
        return original(scope)
    monkeypatch.setattr(balance, "refresh_scope", fresh)
    response = client.get(f"/api/v1/accounts/{accounts[0].id}/balance-summary", headers=headers(member))
    assert response.status_code == 403 and "calculated_balance_cents" not in response.text
    assert store.get_account(accounts[0].id).balance == 98 and store.get_booking(next(iter(store.bookings)) if not hasattr(store, "db") else store.list_bookings()[0].id).amount == .01


def test_real_sql_snapshot_includes_one_consistent_account_and_booking_version(ledger, monkeypatch):
    store, accounts, _, _, _, _, engine = ledger
    if not hasattr(store, "db"):
        pytest.skip("Requires a real independent SQL write during a read snapshot")
    monkeypatch.setattr(balance, "BATCH_SIZE", 1)
    first = booking(store, accounts[0], .01, day=1)
    second = booking(store, accounts[0], .02, day=2)
    writer = create_engine(engine.url, hide_parameters=True)
    batches = 0
    def mutate(connection, cursor, statement, parameters, context, executemany):
        nonlocal batches
        if "FROM bookings" in statement and "ORDER BY" in statement:
            batches += 1
            if batches == 2:
                with writer.begin() as db:
                    db.execute(text("UPDATE accounts SET opening_balance=900, balance=100 WHERE id=:id"), {"id": accounts[0].id})
                    db.execute(text("UPDATE bookings SET amount=8.50 WHERE id=:id"), {"id": second.id})
    event.listen(engine, "before_cursor_execute", mutate)
    try:
        original = balance.account_balance(store, accounts[0].id)
    finally:
        event.remove(engine, "before_cursor_execute", mutate)
        writer.dispose()
    assert original["opening_balance_cents"] == "10005" and original["bookings_sum_cents"] == "3"
    assert original["calculated_balance_cents"] == "10008" and original["comparison_balance_cents"] == "9800"
    current = balance.account_balance(store, accounts[0].id)
    assert current["calculated_balance_cents"] == "90851" and current["source_hash"] != original["source_hash"]
    assert store.get_booking(first.id).amount == .01
    assert engine.pool.checkedout() <= 1


@pytest.mark.parametrize("opening, comparison, amounts, expected_cash, expected_balance, expected_difference", [
    (100, 120, [25, -7], "1800", "11800", "-200"),
    (0, 0, [], "0", "0", "0"),
    (-10, -14, [-2, -3], "-500", "-1500", "-100"),
    (-5, -1, [10], "1000", "500", "600"),
])
def test_independently_reviewed_cash_fixtures(ledger, opening, comparison, amounts, expected_cash, expected_balance, expected_difference):
    store, accounts, *_ = ledger
    account = accounts[0]
    corrupt(store, account, opening, "opening_balance")
    corrupt(store, account, comparison, "comparison_balance")
    for amount in amounts:
        booking(store, account, amount)
    result = balance.account_balance(store, account.id)
    assert (result["bookings_sum_cents"], result["calculated_balance_cents"], result["difference_cents"]) == (
        expected_cash, expected_balance, expected_difference)


def test_source_paging_is_bound_to_account_cutoff_view_and_grants_without_count_or_offset(ledger, monkeypatch):
    store, accounts, _, client, owner, member, engine = ledger
    monkeypatch.setattr(balance, "BATCH_SIZE", 2)
    for index in range(7):
        booking(store, accounts[0], .01, identifier=f"same-date-{index}")
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        token = headers(owner)
        first = client.get(f"/api/v1/accounts/{accounts[0].id}/balance-sources?page_size=2", headers=token).json()
        cursor = first["next_cursor"]
        ids = [item["id"] for item in first["items"]]
        while cursor:
            response = client.get(f"/api/v1/accounts/{accounts[0].id}/balance-sources", params={"cursor": cursor, "page_size": 2}, headers=token)
            assert response.status_code == 200
            value = response.json()
            ids += [item["id"] for item in value["items"]]
            cursor = value["next_cursor"]
        assert len(ids) == len(set(ids)) == 7
        assert ids == sorted(ids, key=str.encode)
        for account_id, params, actor in [
            (accounts[1].id, {}, owner), (accounts[0].id, {"as_of": "2026-01-01"}, owner),
            (accounts[0].id, {"kind": "issues"}, owner), (accounts[0].id, {}, member),
        ]:
            response = client.get(f"/api/v1/accounts/{account_id}/balance-sources", params={"cursor": first["next_cursor"], **params}, headers=headers(actor))
            assert response.status_code == 400 and response.json()["error"]["code"] == "balance_cursor_invalid"
        malformed = client.get(f"/api/v1/accounts/{accounts[0].id}/balance-sources", params={"cursor": "not-a-signed-cursor"}, headers=token)
        assert malformed.status_code == 400
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    # Keyset queries use bounded LIMIT; SQLAlchemy emits OFFSET 0 on SQLite,
    # but never a growing offset or an aggregate COUNT for this projection.
    assert not any("count(" in statement.lower() for statement in statements if "bookings" in statement)


def test_real_bank_payment_and_reversal_do_not_duplicate_or_remove_stored_cash(ledger):
    store, accounts, portfolios, *_ = ledger
    prop = store.create_property(PropertyCreate(portfolio_id=portfolios[0].id, name="Synthetic paid property", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="Synthetic paid unit", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Synthetic cash tenant"))
    contract = store.create_contract(ContractCreate(contract_number="Cash-proof", property_id=prop.id, unit_id=unit.id,
        tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    target = store.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2026, 1, 2), amount_due=25))
    cash = booking(store, accounts[0], 25)
    initial = balance.account_balance(store, accounts[0].id)
    receipt = store.record_payment("receivable", target.id, PaymentCreate(idempotency_key="cash-proof", amount="25.00", payment_date=date(2026, 1, 2), booking_id=cash.id))
    assert store.get_receivable(target.id).amount_paid == 25
    assert balance.account_balance(store, accounts[0].id)["calculated_balance_cents"] == initial["calculated_balance_cents"] == "12505"
    store.reverse_payment("receivable", target.id, receipt.id, PaymentReversalCreate(idempotency_key="reverse-cash-proof", reversal_date=date(2026, 1, 3), reason="Synthetic allocation correction"))
    assert store.get_receivable(target.id).amount_paid == 0
    assert balance.account_balance(store, accounts[0].id)["calculated_balance_cents"] == "12505"
    assert store.get_booking(cash.id).amount == 25


def test_invalid_account_values_can_be_explicitly_repaired_by_existing_patch_with_original_revision(ledger):
    store, accounts, _, client, owner, *_ = ledger
    account = accounts[0]
    corrupt(store, account, "NaN", "opening_balance")
    corrupt(store, account, "NaN", "comparison_balance")
    summary = client.get(f"/api/v1/accounts/{account.id}/balance-summary", headers=headers(owner)).json()
    assert summary["issues_count"] == 2 and summary["calculated_balance_cents"] is None
    guarded = {**headers(owner), "If-Match": etag("accounts", account.id, summary["account_updated_at"])}
    repaired = client.patch(f"/api/v1/accounts/{account.id}", json={"opening_balance": 10, "balance": 20}, headers=guarded)
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["name"] == account.name and repaired.json()["portfolio_id"] == account.portfolio_id
    current = client.get(f"/api/v1/accounts/{account.id}/balance-summary", headers=headers(owner)).json()
    assert current["calculated_balance_cents"] == "1000" and current["issues_count"] == 0
    assert client.patch(f"/api/v1/accounts/{account.id}", json={"opening_balance": 999}, headers=guarded).status_code == 412
    assert store.get_account(account.id).opening_balance == 10


def test_sql_source_ownership_change_after_first_batch_refuses_entire_projection_and_closes_snapshot(ledger, monkeypatch):
    store, accounts, _, _, _, _, engine = ledger
    if not hasattr(store, "db"):
        pytest.skip("Requires independent SQL writers during a bounded snapshot")
    first = booking(store, accounts[0], .01, day=1)
    booking(store, accounts[0], .02, day=2)
    monkeypatch.setattr(balance, "BATCH_SIZE", 1)
    original = balance._live
    calls = 0
    def move(engine, account, rows, scope):
        nonlocal calls
        calls += 1
        if calls == 2:
            with engine.begin() as db:
                db.execute(text("UPDATE bookings SET account_id=:account WHERE id=:id"), {"account": accounts[1].id, "id": first.id})
        return original(engine, account, rows, scope)
    monkeypatch.setattr(balance, "_live", move)
    with pytest.raises(HTTPException) as error:
        balance.account_balance(store, accounts[0].id)
    assert error.value.status_code == 403 and first.id not in error.value.detail
    assert engine.pool.checkedout() <= 1
    assert store.get_account(accounts[0].id).balance == 98
    monkeypatch.setattr(balance, "_live", original)
    assert balance.account_balance(store, accounts[0].id)["bookings_sum_cents"] == "2"


def test_pg_real_repeatable_read_and_current_parent_checks(postgres_database, monkeypatch):  # noqa: F811
    engine, factory, *_ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    with factory() as db:
        store = SQLAlchemyStore(db)
        monkeypatch.setattr(dependencies, "store", store)
        with scope_context(None):
            portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic PG bank"))
            account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Synthetic PG account", account_type="bank", opening_balance=100.05, balance=98))
        first = booking(store, account, .01, day=1)
        second = booking(store, account, .02, day=2)
        original = balance._live
        calls = 0
        def change(engine, captured_account, rows, scope):
            nonlocal calls
            calls += 1
            if calls == 2:
                with engine.begin() as writer:
                    writer.execute(text("UPDATE bookings SET amount=8.50 WHERE id=:id"), {"id": second.id})
            return original(engine, captured_account, rows, scope)
        monkeypatch.setattr(balance, "BATCH_SIZE", 1)
        monkeypatch.setattr(balance, "_live", change)
        old = balance.account_balance(store, account.id)
        assert old["bookings_sum_cents"] == "3" and old["calculated_balance_cents"] == "10008"
        monkeypatch.setattr(balance, "_live", original)
        assert balance.account_balance(store, account.id)["bookings_sum_cents"] == "851"
        assert store.get_booking(first.id).amount == .01
    assert engine.pool.checkedout() == 0
