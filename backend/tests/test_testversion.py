"""Test version: master logins by e-mail and the realistic data set (backend.testversion)."""

import os
from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data
from backend.testversion import seed_testversion
from backend.testversion.builder import Builder
from backend.testversion.dataset import MASTERS, PASSWORD, build_properties

TODAY = date(2026, 10, 5)


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    yield TestClient(app)
    clear_users()
    clear_business_data(store)


def _login(client, name, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": name, "password": password})


def test_users_sign_in_with_username_or_e_mail_address(client):
    register_user("linda.reiser", "linda_reiser@web.de", "Linda Reiser", PASSWORD, "eigentuemer")

    assert _login(client, "linda.reiser").status_code == 200
    assert _login(client, "linda_reiser@web.de").status_code == 200
    assert _login(client, "  Linda_Reiser@WEB.de ").status_code == 200
    assert _login(client, "linda_reiser@web.de", "falsch").status_code == 401
    assert _login(client, "niemand@web.de").status_code == 401


@pytest.mark.skipif(os.environ.get("TEST_STORE_BACKEND", "memory") != "memory",
                    reason="the SQL store keeps e-mail addresses unique")
def test_an_e_mail_address_used_twice_signs_in_no_one(client):
    register_user("a", "same@example.com", "A", PASSWORD, "verwalter")
    register_user("b", "same@example.com", "B", PASSWORD, "verwalter")

    assert _login(client, "same@example.com").status_code == 401
    assert _login(client, "a").status_code == 200


def test_the_portfolio_has_fifteen_properties():
    import random

    props = build_properties(random.Random(15))

    assert len(props) == 15
    assert len({p.name for p in props}) == 15
    assert sum(len(p.units) for p in props) == 93
    assert {p.property_type for p in props} >= {"multi_family", "mixed", "commercial", "condominium",
                                                "single_family", "parking"}


@pytest.mark.skipif(os.environ.get("TEST_STORE_BACKEND", "memory") != "memory",
                    reason="builds three years of history; once (in-memory store) is enough")
def test_the_test_version_builds_a_consistent_history(client):
    """The whole data set through the current API: catches endpoints the test version no longer fits."""
    assert seed_testversion(app, today=TODAY, progress=lambda message: None)
    assert not seed_testversion(app, today=TODAY, progress=lambda message: None)   # only into an empty database

    master = _login(client, MASTERS[1][1]).json()["access_token"]
    headers = {"Authorization": f"Bearer {master}"}

    def get(path):
        return client.get(f"/api/v1{path}", headers=headers).json()

    assert len(get("/properties?limit=1000")) == 15
    units = get("/units?limit=1000")
    assert Counter(u["status"] for u in units) == {"occupied": 91, "vacant": 2}
    review = Counter(item["kind"] for item in get("/review")["items"])
    assert review == {"payment_without_tenant": 2, "adjustment_not_applied": 1}
    periods = Counter((p["label"], p["status"]) for p in get("/billing/periods?limit=1000"))
    assert periods[("Betriebskosten 2025", "draft")] == 2 and periods[("Betriebskosten 2024", "finalized")] == 10
    # accounts are balanced except the stories the tester meets: arrears, a partial payer,
    # rents not yet in this month (late payers, the two payments without tenant)
    open_accounts = []
    for tenant in get("/tenants?limit=1000"):
        account = get(f"/tenants/{tenant['id']}/account?as_of={TODAY.isoformat()}")
        outstanding = sum(row["outstanding"] for row in account["contracts"])
        assert sum(row["overpaid"] for row in account["contracts"]) < 0.01, tenant["full_name"]
        if outstanding > 0.01:
            open_accounts.append(outstanding)
    assert max(open_accounts) > 1000          # four months of arrears
    assert len(open_accounts) <= 12
    assert get("/dashboard/stats")["active_contracts_missing_documents"] == 0


def test_builder_plans_the_stories_for_the_tester():
    builder = Builder(client=None, headers={}, today=TODAY)
    builder.plan()
    behaviours = Counter(t.behaviour for t in builder.tenancies)

    assert behaviours["arrears"] == 1 and behaviours["partial"] == 1 and behaviours["unassigned"] == 2
    assert all(t.start < builder.start for t in builder.tenancies if t.start.year < 2023)
    future = [t for t in builder.tenancies if t.start > TODAY]
    assert len(future) == 1                    # the successor who signed already


def test_uploads_are_stored_where_the_app_serves_them(tmp_path, monkeypatch):
    """The Windows program changes into its install folder: a relative "uploads" folder put
    uploaded documents there, while /uploads served the data folder (404 on every document)."""
    from backend.paths import get_uploads_dir
    from backend.services.file_storage import LocalStorage

    monkeypatch.chdir(tmp_path)
    storage = LocalStorage()

    assert storage.base_dir == get_uploads_dir()
    assert not (tmp_path / "uploads").exists()
