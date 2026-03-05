from fastapi import FastAPI

from backend import app as app_module


def test_mount_contract_wizard_if_available_calls_mount(monkeypatch):
    mounted = {}

    def _fake_mount(app, mount_path, static_path):
        mounted["app"] = app
        mounted["mount_path"] = mount_path
        mounted["static_path"] = static_path

    monkeypatch.setattr(app_module, "_load_contract_wizard_mount", lambda: _fake_mount)

    test_app = FastAPI()
    app_module._mount_contract_wizard_if_available(test_app)

    assert mounted["app"] is test_app
    assert mounted["mount_path"] == "/mietvertrag"
    assert mounted["static_path"] == "/mietvertrag/static"


def test_mount_contract_wizard_if_available_skips_when_missing(monkeypatch):
    monkeypatch.setattr(app_module, "_load_contract_wizard_mount", lambda: None)

    test_app = FastAPI()
    app_module._mount_contract_wizard_if_available(test_app)
