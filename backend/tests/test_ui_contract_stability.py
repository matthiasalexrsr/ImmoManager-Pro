"""UI fields survive arbitrary imports and additive legacy schema upgrades."""

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

from backend.compat.ui_contracts import ensure_ui_contract_schema


@pytest.mark.parametrize("store_first", [False, True])
def test_model_references_remain_identical_before_and_after_application_import(store_first):
    script = '''
from backend import models
references = {name: getattr(models, name) for name in ("Invoice", "InvoiceCreate", "Receivable", "ReceivableCreate", "Meter", "MeterCreate")}
if STORE_FIRST:
    import backend.storage
    import backend.repositories.finance_repo
import backend.dependencies
from backend.compat.ui_contracts import ensure_ui_contracts
ensure_ui_contracts()
assert all(reference is getattr(models, name) for name, reference in references.items())
invoice = references["InvoiceCreate"](supplier="Synthetic", invoice_date="2026-01-01", net_amount=1, gross_amount=1, invoice_number="NUMBER", payment_reference="REFERENCE", notes="NOTE", category="CATEGORY")
assert invoice.model_dump()["invoice_number"] == "NUMBER"
assert references["ReceivableCreate"](contract_id="synthetic", due_date="2026-01-01", amount_due=1, description="DESCRIPTION").description == "DESCRIPTION"
assert references["MeterCreate"](unit_id="synthetic", meter_type="water", contract_number="CONTRACT", contract_end_date="2026-12-31").contract_number == "CONTRACT"
'''.replace("STORE_FIRST", repr(store_first))
    env = {**os.environ, "SQLITE_PERSISTENT_STORE": "false", "ALLOW_INMEMORY_FALLBACK": "true"}
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr


def test_legacy_ui_columns_are_added_repeatably_without_changing_rows(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "legacy-ui.db").as_posix())
    try:
        with engine.begin() as connection:
            for table in ("receivables", "invoices", "meters"):
                connection.execute(text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, legacy_note TEXT)"))
                connection.execute(text(f"INSERT INTO {table} VALUES ('synthetic', 'PRESERVE')"))
            ensure_ui_contract_schema(connection)
            ensure_ui_contract_schema(connection)
            for table in ("receivables", "invoices", "meters"):
                assert connection.execute(text(f"SELECT id, legacy_note FROM {table}")).one() == ("synthetic", "PRESERVE")
            assert "invoice_number" in {c["name"] for c in inspect(connection).get_columns("invoices")}
    finally:
        engine.dispose()
