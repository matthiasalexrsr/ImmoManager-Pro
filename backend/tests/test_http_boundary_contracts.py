"""Browser/LAN/proxy boundary contracts with an independent minimal HTTP app."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings
from backend.services.http_boundary import HTTPBoundaryMiddleware, authority, configured_hosts


@pytest.fixture
def boundary():
    app = FastAPI()
    calls = []

    @app.api_route("/probe", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def probe():
        calls.append(True)
        return {"ok": True}

    app.add_middleware(HTTPBoundaryMiddleware,
                       allowed_hosts=["testserver", "127.0.0.1", "::1", "verwaltung.example.invalid", "192.168.1.20"],
                       allowed_origins=["http://localhost:5173"])
    with TestClient(app, base_url="https://testserver") as client:
        yield client, calls


@pytest.mark.parametrize("host", ["TESTSERVER", "testserver:443", "127.0.0.1:8765", "[::1]:8765",
                                  "[0:0:0:0:0:0:0:1]:8765", "verwaltung.example.invalid", "192.168.1.20:8765"])
def test_loopback_explicit_lan_and_proxy_hosts_work(boundary, host):
    client, calls = boundary
    assert client.post("/probe", headers={"Host": host}).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("host", ["testserver.evil.invalid", "evil.testserver", "evil.invalid:8765",
                                  "testserver?", "testserver/", "testserver#", "testserver:0", "testserver:99999",
                                  "testserver:", "[::1]evil", "[::1]@evil.invalid", "testserver..", "user@testserver"])
def test_invalid_or_untrusted_host_never_reaches_endpoint(boundary, host):
    client, calls = boundary
    assert client.post("/probe", headers={"Host": host}).status_code == 400
    assert calls == []


def test_duplicate_host_or_origin_is_rejected(boundary):
    client, calls = boundary
    assert client.post("/probe", headers=[("Host", "testserver"), ("Host", "evil.invalid")]).status_code == 400
    assert client.post("/probe", headers=[("Origin", "https://testserver"), ("Origin", "https://evil.invalid")]).status_code == 403
    assert calls == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("origin", ["https://foreign.invalid", "null", "https://testserver:444", "https://testserver/path",
                                    "https://testserver#fragment", "https://testserver?query", "https://user@testserver"])
def test_unsafe_foreign_null_or_malformed_origin_is_refused(boundary, method, origin):
    client, calls = boundary
    assert client.request(method, "/probe", headers={"Origin": origin}).status_code == 403
    assert calls == []


@pytest.mark.parametrize("origin", ["https://testserver", "https://testserver:443", "http://localhost:5173"])
def test_same_origin_and_configured_development_ui_work(boundary, origin):
    client, calls = boundary
    assert client.post("/probe", headers={"Origin": origin, "Sec-Fetch-Site": "cross-site"}).status_code == 200
    assert len(calls) == 1


def test_no_origin_api_clients_work_but_cross_site_fetch_without_origin_does_not(boundary):
    client, calls = boundary
    assert client.post("/probe").status_code == 200
    assert client.post("/probe", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/probe", headers={"Origin": "https://foreign.invalid"}).status_code == 200
    assert len(calls) == 2  # Cross-origin reads remain the existing CORS/auth boundary.


def test_host_configuration_is_exact_and_portal_path_does_not_break_proxy():
    hosts = configured_hosts(["192.168.1.20", "api.example.invalid"], ["https://verwaltung.example.invalid"],
                             "https://portal.example.invalid/portal", production=True)
    assert set(hosts) == {"localhost", "127.0.0.1", "::1", "192.168.1.20", "api.example.invalid",
                          "verwaltung.example.invalid", "portal.example.invalid"}
    assert "testserver" not in hosts
    assert "testserver" in configured_hosts([], [], "", production=False)


@pytest.mark.parametrize("value", ["*", "*.example.invalid", "https://example.invalid", "example.invalid:8765",
                                    "[::1]evil", "user@example.invalid", "example.invalid/", "example.invalid#"])
def test_settings_refuse_wildcard_urls_ports_or_malformed_trusted_hosts(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, trusted_hosts=[value])  # type: ignore[call-arg]


def test_trusted_hosts_accept_json_and_csv_environment_lists(monkeypatch):
    monkeypatch.setenv("TRUSTED_HOSTS", 'api.example.invalid,192.168.1.20,[::1]')
    assert Settings(_env_file=None).trusted_hosts == ["api.example.invalid", "192.168.1.20", "[::1]"]  # type: ignore[call-arg]
    monkeypatch.setenv("TRUSTED_HOSTS", '["api.example.invalid", "192.168.1.20"]')
    assert Settings(_env_file=None).trusted_hosts == ["api.example.invalid", "192.168.1.20"]  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["", "localhost\x00", "[::1]suffix", "[::1]:", "[::1]:80:90"])
def test_authority_rejects_ambiguous_ascii_parser_inputs(value):
    with pytest.raises(ValueError):
        authority(value)
