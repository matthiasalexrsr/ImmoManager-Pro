from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import app as app_module


def _dummy_build_pdf(data):
    return b"%PDF-dummy"


def _pkg_path():
    return (
        Path(__file__).resolve().parent.parent.parent
        / "mietvertrag_wizard_fastapi_reportlab_pro"
        / "mietvertrag_wizard"
    )


def test_mount_contract_wizard_if_available_mounts_sub_app(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_load_contract_wizard_mount",
        lambda: (_dummy_build_pdf, _pkg_path()),
    )

    test_app = FastAPI()
    app_module._mount_contract_wizard_if_available(test_app)

    # Verify a Mount was added at /mietvertrag
    mount_paths = [r.path for r in test_app.routes if hasattr(r, "app")]
    assert "/mietvertrag" in mount_paths


def test_mount_contract_wizard_if_available_skips_when_missing(monkeypatch):
    monkeypatch.setattr(app_module, "_load_contract_wizard_mount", lambda: None)

    test_app = FastAPI()
    app_module._mount_contract_wizard_if_available(test_app)

    mount_paths = [r.path for r in test_app.routes if hasattr(r, "app")]
    assert "/mietvertrag" not in mount_paths


def test_wizard_endpoints_functional(monkeypatch):
    """Verify the wizard HTML page and PDF endpoint work end-to-end."""
    monkeypatch.setattr(
        app_module,
        "_load_contract_wizard_mount",
        lambda: (_dummy_build_pdf, _pkg_path()),
    )

    test_app = FastAPI()
    app_module._mount_contract_wizard_if_available(test_app)
    client = TestClient(test_app)

    # Wizard HTML page
    r = client.get("/mietvertrag/")
    assert r.status_code == 200
    assert "Mietvertrag Wizard" in r.text

    # PDF endpoint
    r2 = client.post("/mietvertrag/api/pdf", json={"vermieter": [{"name": "V"}]})
    assert r2.status_code == 200
    assert r2.content == b"%PDF-dummy"


def test_mietvertrag_no_slash_redirects(monkeypatch):
    """GET /mietvertrag (no trailing slash) should redirect to /mietvertrag/."""
    monkeypatch.setattr(
        app_module,
        "_load_contract_wizard_mount",
        lambda: (_dummy_build_pdf, _pkg_path()),
    )

    test_app = FastAPI()
    app_module._mount_contract_wizard_if_available(test_app)
    client = TestClient(test_app, follow_redirects=False)

    r = client.get("/mietvertrag")
    assert r.status_code == 301
    assert r.headers["location"] == "/mietvertrag/"
