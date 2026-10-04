"""UI field extensions must apply no matter which module is imported first."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("entry", ["backend.storage", "backend.models", "backend.dependencies", "backend.app"])
def test_in_memory_store_keeps_ui_fields(entry):
    code = (
        f"import {entry}\n"
        "from backend.storage import InMemoryStore\n"
        "from backend.models import InvoiceCreate\n"
        "inv = InMemoryStore().create_invoice(InvoiceCreate(supplier='X', invoice_date='2026-01-01',"
        " net_amount=1, gross_amount=1, invoice_number='RE-1'))\n"
        "assert inv.invoice_number == 'RE-1', inv\n"
    )
    env = {"PYTHONPATH": str(ROOT), "SQLITE_PERSISTENT_STORE": "false", "ALLOW_INMEMORY_FALLBACK": "true",
           "PATH": "/usr/bin:/bin"}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
