"""UI field extensions must apply no matter which module is imported first."""

import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from tools.xstress.core import isolated_env

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("entry", ["backend.storage", "backend.models", "backend.dependencies", "backend.app"])
def test_in_memory_store_keeps_ui_fields(entry, tmp_path):
    code = (
        f"import {entry}\n"
        "from backend.storage import InMemoryStore\n"
        "from backend.models import InvoiceCreate\n"
        "inv = InMemoryStore().create_invoice(InvoiceCreate(supplier='X', invoice_date='2026-01-01',"
        " net_amount=1, gross_amount=1, invoice_number='RE-1'))\n"
        "assert inv.invoice_number == 'RE-1', inv\n"
    )
    env = isolated_env(tmp_path, secret=secrets.token_urlsafe(48), persistent=False)
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
                            timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr[-2000:]
