"""Real file staging, exact cents, rollback/replay and parallel publication."""
import io
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.bank_import_models import BankImportORM, BankImportReceiptORM, BankImportRowORM, BankImportSourceORM
from backend.db.bank_import_schema import ensure_bank_import_schema
from backend.db.orm_models import Base, BookingORM
from backend.models import AccountCreate, PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.bank_import import (
    BankConfirm,
    BankImportError,
    commit_import,
    get_import,
    preview_import,
    stage_import,
)
from backend.services.bank_import_parser import BankMapping, BankParseError, amount_cents, parse_rows
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sql"])
def bank_store(request, tmp_path):
    if request.param == "memory":
        store = InMemoryStore()
        yield store
        if hasattr(store, "_bank_import_engine"):
            store._bank_import_engine.dispose()
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'bank.db'}", connect_args={"timeout": 30, "check_same_thread": False})
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            ensure_bank_import_schema(connection)
        with Session(engine) as session:
            yield SQLAlchemyStore(session)
        engine.dispose()


def account(store, name="Synthetic bank"):
    portfolio = store.create_portfolio(PortfolioCreate(name=name))
    return store.create_account(AccountCreate(portfolio_id=portfolio.id, name=name, account_type="bank", iban="DE89370400440532013000"))


def stage(store, account_id, body, mapping=None):
    return stage_import(store, io.BytesIO(body.encode("utf-8")), account_id, mapping or BankMapping())


def confirm(store, job):
    return commit_import(store, job["id"], BankConfirm(revision=job["revision"], preview_hash=job["preview_hash"]))


def test_equal_legitimate_rows_exact_cents_replay_and_restart(bank_store):
    selected = account(bank_store)
    original = "date;amount;text\n2026-01-01;0.10;Same text\n2026-01-01;0,10;Same text\n2026-01-02;-1.23;Expense\n"
    job = stage(bank_store, selected.id, original)
    assert job["state"] == "ready" and job["row_count"] == 3
    assert bank_store.list_bookings() == []
    first = preview_import(bank_store, job["id"], page_size=2)
    assert [row["amount_cents"] for row in first["items"]] == [10, 10]
    assert first["items"][0]["fingerprint"] != first["items"][1]["fingerprint"]
    second = preview_import(bank_store, job["id"], page_size=2, cursor=first["next_cursor"])
    assert second["items"][0]["amount_cents"] == -123 and not second["has_more"]
    if hasattr(bank_store, "db"):
        engine = bank_store.db.get_bind()
        bank_store.db.close()
        bank_store.db = Session(engine)
    assert get_import(bank_store, job["id"])["preview_hash"] == job["preview_hash"]
    result = confirm(bank_store, job)
    assert result["published_count"] == 3 and result["state"] == "committed"
    assert sum(Decimal(str(row.amount)) for row in bank_store.list_bookings()) == Decimal("-1.03")
    assert confirm(bank_store, job)["replay"]
    assert stage(bank_store, selected.id, original)["id"] == job["id"]
    assert len(bank_store.list_bookings()) == 3


def test_all_errors_are_persisted_no_partial_publication(bank_store):
    selected = account(bank_store)
    job = stage(bank_store, selected.id, "date;amount;text\nwrong;2;Invalid date\n2026-01-01;1.001;Invalid cents\n2026-01-01;1.00;Valid\n")
    assert job["state"] == "invalid" and job["error_count"] == 2 and job["row_count"] == 3
    errors = preview_import(bank_store, job["id"], errors_only=True, page_size=1)
    assert errors["items"][0]["error_code"] == "DATE_INVALID"
    later = preview_import(bank_store, job["id"], errors_only=True, page_size=1, cursor=errors["next_cursor"])
    assert later["items"][0]["error_code"] == "AMOUNT_INVALID"
    with pytest.raises(BankImportError) as error:
        confirm(bank_store, job)
    assert error.value.code == "BANK_PREVIEW_INVALID"
    assert not bank_store.list_bookings()


def test_mapping_and_preview_token_are_bound_not_guessable(bank_store):
    selected = account(bank_store)
    mapping = BankMapping(date_column="Datum", amount_column="Betrag", text_column="Zweck",
        date_format="%d.%m.%Y", decimal_separator=",", thousands_separator=".")
    job = stage(bank_store, selected.id, "Datum;Betrag;Zweck\n01.01.2026;1.234,56;Quoted \"text\"\n02.01.2026;-12,34;Next", mapping)
    assert preview_import(bank_store, job["id"])["items"][0]["amount_cents"] == 123456
    first = preview_import(bank_store, job["id"], page_size=1)
    for kwargs in ({"page_size": 2, "cursor": first["next_cursor"]},
                   {"page_size": 1, "cursor": first["next_cursor"][:-1] + "X"}):
        with pytest.raises(BankImportError) as error:
            preview_import(bank_store, job["id"], **kwargs)
        assert error.value.code == "BANK_CURSOR_INVALID"
    with pytest.raises(BankImportError):
        commit_import(bank_store, job["id"], BankConfirm(revision=0, preview_hash="0" * 64))
    assert not bank_store.list_bookings()


def test_bank_reference_overlap_is_provenanced_content_conflict_not_swallowed(bank_store):
    selected = account(bank_store)
    mapping = BankMapping(reference_column="id")
    first = stage(bank_store, selected.id, "date;amount;text;id\n2026-01-01;10;A;BANK1\n2026-01-01;10;A;BANK2\n", mapping)
    assert confirm(bank_store, first)["published_count"] == 2
    overlap = stage(bank_store, selected.id, "date;amount;text;id\n2026-01-01;10;A;BANK2\n2026-01-02;20;B;BANK3\n", mapping)
    assert overlap["duplicate_count"] == 1
    assert confirm(bank_store, overlap)["published_count"] == 1
    assert len(bank_store.list_bookings()) == 3
    conflict = stage(bank_store, selected.id, "date;amount;text;id\n2026-01-01;99;Changed;BANK1\n", mapping)
    assert conflict["error_count"] == 1
    assert preview_import(bank_store, conflict["id"])["items"][0]["error_code"] == "BANK_IDENTITY_CONFLICT"
    repeated = stage(bank_store, selected.id, "date;amount;text;id\n2026-01-03;30;C;BANK4\n2026-01-03;30;C;BANK4\n", mapping)
    assert repeated["error_count"] == 1
    with pytest.raises(BankImportError):
        confirm(bank_store, repeated)
    assert len(bank_store.list_bookings()) == 3


def test_file_without_reference_never_heuristically_drops_another_source(bank_store):
    selected = account(bank_store)
    for text in ("date;amount;text\n2026-01-01;10;A\n", "date;amount;text\r\n2026-01-01;10;A\r\n"):
        assert confirm(bank_store, stage(bank_store, selected.id, text))["published_count"] == 1
    assert len(bank_store.list_bookings()) == 2


def test_identical_file_is_bound_to_its_own_account(bank_store):
    selected = account(bank_store)
    other = bank_store.create_account(AccountCreate(portfolio_id=selected.portfolio_id, name="Other account", account_type="bank"))
    body = "date;amount;text\n2026-01-01;10;Same source\n"
    first = stage(bank_store, selected.id, body)
    second = stage(bank_store, other.id, body)
    assert first["source_sha256"] == second["source_sha256"] and first["id"] != second["id"]
    assert preview_import(bank_store, first["id"])["items"][0]["fingerprint"] != preview_import(bank_store, second["id"])["items"][0]["fingerprint"]
    assert confirm(bank_store, first)["published_count"] == confirm(bank_store, second)["published_count"] == 1


def test_missing_header_empty_source_and_parser_capacity_have_stored_errors(bank_store):
    selected = account(bank_store)
    for source, code in (("amount;text\n1;Missing date", "CSV_HEADER"), ("date;amount;text\n", "EMPTY_FILE"),
                         ('date;amount;text\n2026-01-01;1;"unfinished', "CSV_SYNTAX")):
        job = stage(bank_store, selected.id, source)
        assert job["state"] == "invalid"
        assert preview_import(bank_store, job["id"])["items"][0]["error_code"] == code
        with pytest.raises(BankImportError):
            confirm(bank_store, job)
    assert not bank_store.list_bookings()


def test_sql_failure_after_first_chunk_rolls_back_all_provenance_and_bookings(bank_store, monkeypatch):
    selected = account(bank_store)
    body = "date;amount;text\n" + "2026-01-01;1.01;Synthetic\n" * 501
    job = stage(bank_store, selected.id, body)
    if hasattr(bank_store, "db"):
        bind = bank_store.db.get_bind()
        calls = 0

        def fail_later(_connection, _cursor, statement, _parameters, _context, _many):
            nonlocal calls
            if statement.startswith("INSERT INTO bookings"):
                calls += 1
                if calls == 2:
                    raise RuntimeError("synthetic publication failure")
        event.listen(bind, "before_cursor_execute", fail_later)
        try:
            with pytest.raises(RuntimeError, match="synthetic publication"):
                confirm(bank_store, job)
        finally:
            event.remove(bind, "before_cursor_execute", fail_later)
        assert bank_store.db.scalar(select(func.count()).select_from(BankImportReceiptORM)) == 0
    else:
        from backend.services import bank_import
        original = bank_import._checked_rows
        def fail_later(db, imported):
            iterator = original(db, imported)
            yield next(iterator)
            raise RuntimeError("synthetic publication failure")
        monkeypatch.setattr(bank_import, "_checked_rows", fail_later)
        with pytest.raises(RuntimeError, match="synthetic publication"):
            confirm(bank_store, job)
    assert not bank_store.list_bookings()
    assert get_import(bank_store, job["id"])["revision"] == 0


def test_sql_parallel_confirmation_has_one_atomic_publication(bank_store):
    if not hasattr(bank_store, "db"):
        pytest.skip("Independent SQL transactions")
    selected = account(bank_store)
    job = stage(bank_store, selected.id, "date;amount;text\n2026-01-01;1;Parallel\n")
    engine = bank_store.db.get_bind()
    bank_store.db.rollback()
    barrier = Barrier(2)
    def worker():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return confirm(SQLAlchemyStore(db), job)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))
    assert sorted(result["replay"] for result in results) == [False, True]
    assert bank_store.db.scalar(select(func.count()).select_from(BookingORM)) == 1
    assert bank_store.db.scalar(select(func.count()).select_from(BankImportReceiptORM)) == 1


def test_source_and_preview_rows_are_immutable_at_sql_layer(bank_store):
    if not hasattr(bank_store, "db"):
        pytest.skip("Actual SQL trigger protection")
    selected = account(bank_store)
    job = stage(bank_store, selected.id, "date;amount;text\n2026-01-01;1;Immutable\n")
    for model, changes in ((BankImportRowORM, {"amount_cents": 999}), (BankImportSourceORM, {"data": b"changed"})):
        with pytest.raises(IntegrityError, match="immutable"):
            bank_store.db.query(model).filter(model.import_id == job["id"]).update(changes)
        bank_store.db.rollback()
    with pytest.raises(IntegrityError, match="immutable"):
        bank_store.db.query(BankImportORM).filter(BankImportORM.id == job["id"]).update({"mapping_hash": "0" * 64})
    bank_store.db.rollback()
    assert confirm(bank_store, job)["published_count"] == 1


def test_mt940_each_physical_transaction_reversals_account_and_balance_validation(bank_store):
    selected = account(bank_store)
    source = ":20:EXAMPLE\n:25:DE89370400440532013000\n:28C:1/1\n:60F:C260101EUR100,00\n:61:2601020102D12,50NTRFNONREF\n:86:Same\n:61:2601020102D12,50NTRFNONREF\n:86:Same\n:61:2601020102RC1,00NTRFREF//BANK-1\n:86:Credit reversal\n:61:2601020102RD2,00NTRFREF//BANK-2\n:86:Debit reversal\n:62F:C260102EUR76,00\n"
    job = stage(bank_store, selected.id, source, BankMapping(format="mt940"))
    assert job["state"] == "ready" and job["row_count"] == 4
    assert [item["amount_cents"] for item in preview_import(bank_store, job["id"])["items"]] == [-1250, -1250, -100, 200]
    assert confirm(bank_store, job)["published_count"] == 4
    for bad, code in ((source.replace("EUR76,00", "EUR77,00"), "MT940_BALANCE_MISMATCH"),
                      (source.replace(selected.iban, "DEOTHER"), "ACCOUNT_MISMATCH"),
                      (source.replace(":62F:C260102EUR76,00\n", ""), "MT940_CLOSING_MISSING")):
        invalid = stage(bank_store, selected.id, bad, BankMapping(format="mt940"))
        assert invalid["state"] == "invalid"
        assert code in {item["error_code"] for item in preview_import(bank_store, invalid["id"])["items"]}
        with pytest.raises(BankImportError):
            confirm(bank_store, invalid)
    assert len(bank_store.list_bookings()) == 4


def test_mt940_statement_position_is_stable_when_export_contains_other_statements(bank_store):
    selected = account(bank_store)
    def statement(reference, number):
        return f":20:{reference}\n:25:{selected.iban}\n:28C:{number}/1\n:60F:C260101EUR100,00\n:61:2601020102C1,00NTRFNONREF\n:86:Same\n:62F:C260102EUR101,00\n"
    first, second = statement("FIRST", 1), statement("SECOND", 2)
    assert confirm(bank_store, stage(bank_store, selected.id, first + second, BankMapping(format="mt940")))["published_count"] == 2
    partial_export = stage(bank_store, selected.id, second, BankMapping(format="mt940"))
    assert partial_export["duplicate_count"] == 1
    assert confirm(bank_store, partial_export)["published_count"] == 0
    assert len(bank_store.list_bookings()) == 2


@pytest.mark.parametrize("value,mapping,expected", [
    ("1.234,56", BankMapping(decimal_separator=",", thousands_separator="."), 123456),
    ("1,234.56", BankMapping(decimal_separator=".", thousands_separator=","), 123456),
    ("-0,01", BankMapping(), -1),
])
def test_explicit_decimal_locale(value, mapping, expected):
    assert amount_cents(value, mapping) == expected


def test_exact_amount_beyond_money_column_is_recoverable_before_publication(bank_store):
    selected = account(bank_store)
    job = stage(bank_store, selected.id, "date;amount;text\n2026-01-01;90071992547409931.23;Large exact amount\n")
    assert job["state"] == "invalid"
    problem = preview_import(bank_store, job["id"])["items"][0]
    assert problem["error_code"] == "AMOUNT_CAPACITY" and "Geldspalte" in problem["error_message"]
    with pytest.raises(BankImportError):
        confirm(bank_store, job)
    assert not bank_store.list_bookings()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e3", "0", "1.234", "1,234.56", "12 00", "--1", ""])
def test_invalid_or_ambiguous_money_is_not_rounded(value):
    with pytest.raises(BankParseError):
        amount_cents(value, BankMapping())


def test_unicode_multiline_csv_is_not_truncated_and_bad_encoding_is_explicit():
    rows = list(parse_rows(io.BytesIO('date;amount;text\n2026-01-01;1.01;"Änderung\nmit Semikolon; Text"\n'.encode("utf-16")), BankMapping(encoding="utf-16")))
    assert len(rows) == 1 and rows[0].amount_cents == 101 and "\n" in rows[0].text
    assert rows[0].source_line == 3
    bad = list(parse_rows(io.BytesIO(b"date;amount;text\n2026-01-01;1;\xff"), BankMapping()))
    assert bad[0].error_code == "ENCODING_INVALID"


def test_unquoted_literal_quote_and_configurable_large_multiline_field():
    body = 'date;amount;text\n2026-01-01;1;A single " literal\n2026-01-02;2;Next\n'
    assert len(list(parse_rows(io.BytesIO(body.encode()), BankMapping(), maximum_field_chars=30))) == 2
    large = "x\n" * 100_000
    body = f'date;amount;text\n2026-01-01;1;"{large}"\n'
    accepted = list(parse_rows(io.BytesIO(body.encode()), BankMapping(), maximum_field_chars=250_000))
    assert len(accepted) == 1 and accepted[0].text == large.strip()
    rejected = list(parse_rows(io.BytesIO(body.encode()), BankMapping(), maximum_field_chars=1000))
    assert rejected[0].error_code == "FIELD_CAPACITY"
