"""Presentation workspace isolation, persistence and side-effect boundaries."""
import json
import os
import subprocess
import sys
from datetime import date

import pytest

from backend import demo


@pytest.fixture
def isolated_environment(monkeypatch):
    # The helper intentionally updates many variables. A private mapping keeps
    # all changes in this test and never changes the runner's OS environment.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    os.environ.pop("IMMO_DEMO", None)


def test_new_demo_ignores_live_paths_and_credentials(tmp_path, isolated_environment):
    real = tmp_path / "live"
    real.mkdir()
    original = real / "customer.sqlite3"
    original.write_bytes(b"caller-owned bytes")
    os.environ.update(DATA_DIR=str(real), DATABASE_URL="sqlite:///" + original.as_posix(), JWT_SECRET_KEY="existing-private-key",
                      SMTP_PASSWORD="existing-private-password", AWS_SECRET_ACCESS_KEY="existing-private-key", SECRET_KEYS="existing-keyring")
    root = demo.configure_environment(tmp_path / "presentation")
    assert root != real and original.read_bytes() == b"caller-owned bytes"
    assert os.environ["DATABASE_URL"] == "sqlite:///" + (root / demo.DATABASE).as_posix()
    assert os.environ["JWT_SECRET_KEY"] != "existing-private-key"
    assert not any(name in os.environ for name in ("SMTP_PASSWORD", "AWS_SECRET_ACCESS_KEY", "SECRET_KEYS"))
    assert os.environ["FILE_STORAGE_BACKEND"] == "local" and os.environ["JOB_SCHEDULER_ENABLED"] == "false"
    assert demo.validate_environment() == root


def test_existing_unmarked_database_is_never_adopted(tmp_path, isolated_environment):
    file = tmp_path / "customer.sqlite3"
    file.write_bytes(b"do not alter")
    with pytest.raises(RuntimeError, match="vorhandener Datenbestand"):
        demo.configure_environment(tmp_path)
    assert file.read_bytes() == b"do not alter" and not (tmp_path / demo.MARKER).exists()


def test_reentry_preserves_marker_key_and_edits(tmp_path, isolated_environment):
    root = demo.configure_environment(tmp_path)
    marker = (root / demo.MARKER).read_bytes()
    key = (root / "demo-auth.key").read_bytes()
    (root / demo.DATABASE).write_bytes(b"presentation edits")
    assert demo.configure_environment(root) == root
    assert (root / demo.MARKER).read_bytes() == marker and (root / "demo-auth.key").read_bytes() == key
    assert (root / demo.DATABASE).read_bytes() == b"presentation edits"


def test_wrong_database_is_refused_before_seed(tmp_path, isolated_environment):
    root = demo.configure_environment(tmp_path)
    os.environ["DATABASE_URL"] = "sqlite:///outside.sqlite3"
    with pytest.raises(RuntimeError, match="Demo-Datenbank"):
        demo.validate_environment()
    assert not (root / demo.DATABASE).exists()


def test_demo_health_credentials_never_appear_without_explicit_demo(tmp_path, isolated_environment):
    assert demo.health_fields() == {"demo": False}
    root = demo.configure_environment(tmp_path)
    assert demo.health_fields()["demo_login"] == {"username":demo.USERNAME, "password":demo.PASSWORD}
    marker = json.loads((root / demo.MARKER).read_text())
    marker["state"] = "complete"
    (root / demo.MARKER).write_text(json.dumps(marker))
    assert demo.health_fields()["demo_ready"]


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/integrations/email/run"), ("POST", "/api/v1/communication/42/confirm"),
    ("POST", "/api/v1/assistant/conversations/42/runs"), ("POST", "/api/v1/updates/apply"),
    ("POST", "/api/v1/banking/connections"), ("POST", "/api/v1/backups/restore"),
])
def test_external_actions_are_stopped_centrally(method, path):
    assert demo.blocked_action(method, path)


@pytest.mark.parametrize("method,path", [
    ("GET", "/health"), ("POST", "/api/v1/documents/import"), ("PATCH", "/api/v1/properties/42"),
    ("POST", "/api/v1/billing/periods/42/generate"), ("POST", "/api/v1/documents/print"),
    ("POST", "/api/v1/communication/drafts"), ("POST", "/api/v1/backups/create"),
])
def test_normal_local_business_work_remains_available(method, path):
    assert not demo.blocked_action(method, path)


def test_network_barrier_is_process_local_and_keeps_asyncio_socketpair(tmp_path):
    code = """
import json,os,socket,sys
from backend.demo import configure_environment,install_backend_guards,DemoOutboundBlocked
configure_environment(sys.argv[1]);install_backend_guards()
for event,args in [('socket.connect',(socket.socket(),('192.0.2.1',25))),('socket.getaddrinfo',('smtp.example.invalid',587,0,0,0))]:
 try:sys.audit(event,*args)
 except DemoOutboundBlocked:pass
 else:raise AssertionError(event)
a,b=socket.socketpair();a.send(b'x');assert b.recv(1)==b'x';a.close();b.close()
import asyncio
assert asyncio.run(asyncio.sleep(0,result='own-loop'))=='own-loop'
print(json.dumps({'network_events_blocked':True,'asyncio_and_socketpair':True}))
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path / "workspace")], capture_output=True, text=True,
                            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["network_events_blocked"]
    assert not demo.enabled()


def test_direct_asgi_demo_flag_cannot_connect_a_live_database(tmp_path):
    data = tmp_path / "live"
    data.mkdir()
    file = data / "customer.sqlite3"
    file.write_bytes(b"untouched")
    env = dict(os.environ, IMMO_DEMO="true", DATA_DIR=str(data), DATABASE_URL="sqlite:///" + file.as_posix())
    result = subprocess.run([sys.executable, "-c", "import backend.config"], capture_output=True, text=True, env=env,
                            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode != 0 and "Demobestand" in result.stderr
    assert file.read_bytes() == b"untouched"


def test_complete_dataset_is_connected_and_contains_real_documents(tmp_path):
    from backend.demo.dataset import seed_dataset
    from backend.storage import InMemoryStore

    store = InMemoryStore()
    summary = seed_dataset(store, tmp_path, today=date(2026, 11, 5))
    assert summary["property"] == 8 and summary["unit"] == 46 and summary["contract"] == 42
    assert summary["booking"] >= 1000 and summary["document"] >= 70 and summary["service_contract"] == 8
    assert {prop.federal_state for prop in store.list_properties()} == {"BW"}
    assert len([meter for meter in store.list_meters() if meter.next_inspection]) == 4
    assert len([contract for contract in store.list_contracts() if contract.end_date]) == 2
    assert all(tenant.email and tenant.email.endswith(".invalid") for tenant in store.list_tenants())
    from pypdf import PdfReader
    for document in store.list_documents():
        file = tmp_path / document.file_url.lstrip("/")
        assert file.is_file() and file.read_bytes().startswith(b"%PDF-")
    first = store.list_documents()[0]
    text = PdfReader(tmp_path / first.file_url.lstrip("/")).pages[0].extract_text()
    assert "Neckarbogen" in text or "NECKARBOGEN" in text
    with pytest.raises(RuntimeError, match="leeren Bestand"):
        seed_dataset(store, tmp_path)
