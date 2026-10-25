"""Every response carries the browser security headers; routes keep their own stricter policy."""

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from backend.config import settings
from backend.middleware import APP_CSP, SecurityHeadersMiddleware
from backend.tests.test_daily_workflows import clean  # noqa: F401
from backend.tests.test_daily_workflows import client as signed_in


def client(base="http://testserver"):
    mini = FastAPI()

    @mini.get("/")
    def page():
        return Response("<!doctype html><title>x</title>", media_type="text/html")

    @mini.get("/api/v1/thing")
    def thing():
        return {"ok": True}

    @mini.get("/uploads/x.html")
    def stored():
        return Response("x", headers={"Content-Security-Policy": "sandbox"})

    @mini.get("/mietvertrag/")
    def wizard():
        return Response("<button onclick=print()>", media_type="text/html")

    mini.add_middleware(SecurityHeadersMiddleware)
    return TestClient(mini, base_url=base)


def test_the_app_page_gets_a_strict_policy_and_no_hsts_over_plain_http():
    response = client().get("/")
    csp = response.headers["content-security-policy"]
    assert csp == APP_CSP
    assert "script-src 'self' 'wasm-unsafe-eval';" in csp and "'unsafe-eval'" not in csp.replace("'wasm-unsafe-eval'", "")
    assert "object-src 'none'" in csp and "frame-ancestors 'self'" in csp and "base-uri 'self'" in csp
    assert "connect-src 'self' blob:;" in csp                                # the PDF preview reads files of the chat
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "geolocation=()" in response.headers["permissions-policy"]
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in response.headers


def test_https_adds_hsts_and_data_is_not_embeddable_elsewhere():
    response = client("https://testserver").get("/api/v1/thing")
    assert response.headers["strict-transport-security"] == f"max-age={settings.hsts_max_age}; includeSubDomains"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"


def test_a_route_keeps_its_own_policy_and_the_wizard_its_inline_handlers():
    assert client().get("/uploads/x.html").headers["content-security-policy"] == "sandbox"
    wizard = client().get("/mietvertrag/").headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline'" in wizard and "frame-ancestors 'self'" in wizard


def test_the_policy_can_be_replaced_or_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "content_security_policy", "default-src 'self' https://files.example")
    assert client().get("/").headers["content-security-policy"] == "default-src 'self' https://files.example"
    monkeypatch.setattr(settings, "security_headers_enabled", False)
    assert "content-security-policy" not in client().get("/").headers


def test_the_api_documentation_is_off_in_production_unless_asked_for():
    from backend.config import Environment, Settings
    assert Settings(environment=Environment.development).api_docs is True
    assert Settings(environment=Environment.production, jwt_secret_key="x" * 64).api_docs is False
    assert Settings(environment=Environment.production, jwt_secret_key="x" * 64, api_docs_enabled=True).api_docs is True


def test_the_settings_link_the_api_schema_only_while_the_documentation_is_on(monkeypatch):
    _, browser = signed_in("schema-owner")
    contract = "/api/v1/auth/users/me/settings/configuration-contract"
    monkeypatch.setattr(settings, "api_docs_enabled", True)
    assert browser.get(contract).json()["api"]["schema"] == "/openapi.json"
    monkeypatch.setattr(settings, "api_docs_enabled", False)
    assert browser.get(contract).json()["api"]["schema"] is None              # no link into the app's 404 page
