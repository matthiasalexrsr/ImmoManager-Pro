"""Independent format checks against official fields, including late failures."""

import csv
import hashlib
import io
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from backend.services import datev_streaming as extf


def profile():
    return extf.Profile(12345, 42, date(2026, 1, 1), 4, "portfolio", "03", 0,
        "reviewed-v1", "Synthetic tax review", {
            ("account", "rent", "income"): extf.Rule("1200", "8200", "EUR", True, "Girokonto"),
            ("account", "cost", "expense"): extf.Rule("1200", "4900", "EUR", True, "Girokonto"),
        })


def batch():
    return extf.Batch(date(2026, 1, 1), date(2026, 12, 31),
        datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc), "synthetic-batch", "Review 2026")


def entry(index=1, **changes):
    return replace(extf.Entry(f"booking-{index:08}", "account", "rent", "portfolio", "portfolio",
        "Girokonto", date(2026, 9, 1), Decimal("750.00"), "confirmed",
        datetime(2026, 9, 1, tzinfo=timezone.utc), "", 'Miete; "Prüfung" €'), **changes)


def rows(prepared):
    content = prepared.path.read_bytes()
    assert b"\xef\xbb\xbf" not in content[:3]
    assert b"\n" not in content.replace(b"\r\n", b"")
    return list(csv.reader(io.StringIO(content.decode("cp1252")), delimiter=";"))


def test_official_125_column_schema_and_real_account_type_are_preserved(tmp_path):
    # Official Muster UTF8 header normalized to CP1252; independently fetched.
    assert hashlib.sha256(";".join(extf.COLUMNS).encode("cp1252")).hexdigest() == "a4c23ec4e0bf463d455ff9ebb5b2435954349b014042497114e72c1de88d8951"
    with extf.prepare_download([entry(), entry(2, category_id="cost", amount="-123.45")], profile(), batch(), spool_dir=tmp_path) as prepared:
        actual = rows(prepared)
        assert len(actual[0]) == 31 and actual[0][:5] == ["EXTF", "700", "21", "Buchungsstapel", "13"]
        assert actual[0][10:16] == ["12345", "42", "20260101", "4", "20260101", "20261231"]
        assert all(len(row) == 125 for row in actual[1:])
        assert actual[2][0:3] == ["750,00", "S", "EUR"]
        assert actual[3][0:3] == ["123,45", "H", "EUR"]
        assert actual[2][6:11] == ["1200", "8200", "", "0109", ""]
        assert actual[2][13] == 'Miete; "Prüfung" €'
        assert actual[2][47:50] == ["Immo-ID", "booking-00000001", "Quellrevision"]
        assert actual[2][113] == "0" and actual[0][20] == "0"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("changes,code", [
    ({"amount": "0"}, "amount_range"), ({"amount": "1.001"}, "subcent_amount"),
    ({"amount": "10000000000.00"}, "amount_range"), ({"amount": "NaN"}, "amount_range"),
    ({"payment_text": "x" * 61}, "text_length_or_type"), ({"payment_text": "Miete\nZeile"}, "control_character"),
    ({"payment_text": "Miete 🏠"}, "not_cp1252"), ({"payment_text": ' =HYPERLINK("evil")'}, "formula_prefix"),
    ({"category_id": "other"}, "missing_rule"), ({"account_type": "Mietkonto"}, "account_type_changed"),
    ({"category_portfolio_id": "foreign"}, "portfolio_mismatch"), ({"status": "open"}, "not_confirmed"),
    ({"document_ref": "invented invoice"}, "text_format"),
])
def test_invalid_row_has_precise_code_and_never_publishes(changes, code, tmp_path):
    with pytest.raises(extf.ExportError) as error:
        extf.prepare_download([entry(**changes)], profile(), batch(), spool_dir=tmp_path)
    assert error.value.code == code and error.value.row == 1
    assert list(tmp_path.iterdir()) == []


def test_late_missing_rule_after_twelve_thousand_rows_never_returns_partial_file(tmp_path):
    def source():
        for index in range(1, 12_002):
            yield entry(index, category_id="missing" if index == 12_001 else "rent")
    with pytest.raises(extf.ExportError) as error:
        extf.prepare_download(source(), profile(), batch(), spool_dir=tmp_path)
    assert (error.value.code, error.value.row) == ("missing_rule", 12_001)
    assert list(tmp_path.iterdir()) == []


def test_maximum_format_amount_and_person_account_are_not_artificially_capped(tmp_path):
    rule = extf.Rule("1200", "10001", "EUR", True, "Mietkonto", "person")
    mapped = replace(profile(), rules={("account", "rent", "income"): rule})
    with extf.prepare_download([entry(amount="9999999999.99", account_type="Mietkonto")], mapped, batch(), spool_dir=tmp_path) as prepared:
        assert rows(prepared)[2][0] == "9999999999,99"
        assert rows(prepared)[2][7] == "10001"


def test_snapshot_bytes_and_preview_reference_repeat_but_unused_mapping_changes_are_detected(tmp_path):
    first = extf.prepare_download([entry()], profile(), batch(), spool_dir=tmp_path)
    try:
        with extf.prepare_download([entry()], profile(), batch(), spool_dir=tmp_path, expected_token=first.token) as second:
            assert first.path.read_bytes() == second.path.read_bytes() and first.sha256 == second.sha256
        rules = dict(profile().rules)
        rules[("account", "cost", "expense")] = replace(rules[("account", "cost", "expense")], counter_gl="4901")
        with pytest.raises(extf.ExportError, match="preview_changed"):
            extf.prepare_download([entry()], replace(profile(), rules=rules), batch(), spool_dir=tmp_path, expected_token=first.token)
    finally:
        first.close()
    assert list(tmp_path.iterdir()) == []


def test_write_failure_and_cancel_remove_private_partial_files(tmp_path, monkeypatch):
    monkeypatch.setattr(extf.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("synthetic disk failure")))
    with pytest.raises(extf.ExportError, match="build_failed"):
        extf.prepare_download([entry()], profile(), batch(), spool_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []
    def cancelled():
        yield entry()
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        extf.prepare_download(cancelled(), profile(), batch(), spool_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_official_header_year_restriction_is_explicit(tmp_path):
    with pytest.raises(extf.ExportError, match="header_date"):
        extf.prepare_download([], replace(profile(), fiscal_start=date(1999, 1, 1)),
            replace(batch(), start=date(1999, 1, 1), end=date(1999, 12, 31)), spool_dir=tmp_path)
