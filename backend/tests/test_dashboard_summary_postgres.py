"""Dedicated UUID-schema PostgreSQL proves actual dashboard reads and authority."""

from datetime import date

import pytest

from backend.services import dashboard_summary as service
from backend.tests.test_contract_workspace import seed
from backend.tests.test_dashboard_summary import (
    add_notice,
    check_contract_and_notification_pages,
    check_task_pages,
    insert_units,
)
from backend.tests.test_dashboard_summary_authority import client_for
from backend.tests.test_housing_confirmation_postgres import postgres_housing as postgres_housing


def test_postgres_complete_10001_counts_with_small_actual_pages(postgres_housing):
    box = postgres_housing
    insert_units(box.store, box.property.id, 10001)
    result = service.dashboard_summary(box.store, service.DashboardQuery(as_of=date(2026, 10, 3)))
    assert result["unit_count"] == result["occupancy"]["total"] == 10002
    assert result["occupancy"]["occupied"] == 4001
    assert all(len(page["items"]) <= 5 for page in result["work_hints"].values())


def test_postgres_target_role_counts_and_scoped_hints_match(postgres_housing, monkeypatch):
    box = postgres_housing
    add_notice(box.store, box.property.id, "role-visible", "readonly")
    add_notice(box.store, box.property.id, "role-foreign", "verwalter")
    hidden, _ = seed(box.store, "foreign-pg")
    add_notice(box.store, hidden.property_id, "portfolio-foreign", "readonly")
    client, _accounts, tokens = client_for(box.store, box.p.id, monkeypatch)
    with client:
        response = client.get("/api/v1/dashboard/stats", headers={"Authorization": "Bearer " + tokens.access_token})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["portfolio_count"] == result["property_count"] == result["unit_count"] == result["contract_count"] == 1
    assert result["notification_count"] == result["unread_notifications"] == 1
    assert [item["title"] for item in result["work_hints"]["notifications"]["items"]] == ["role-visible"]


def test_postgres_contract_window_and_equal_time_notification_keysets(postgres_housing):
    # The existing unrelated housing contract is outside this 90-day window.
    def summary(store, **query):
        return service.dashboard_summary(store, service.DashboardQuery(**query))
    check_contract_and_notification_pages(postgres_housing.store, summary)
    check_task_pages(postgres_housing.store, summary)


@pytest.mark.parametrize("change", ["session", "role", "grants", "activation"])
def test_postgres_real_credentials_and_account_changes_reject_prepared_json(postgres_housing, monkeypatch, change):
    from backend import auth
    from backend.models import TaskCreate
    from backend.routers import dashboard as router
    from backend.services.portfolio_scope import scope_context

    box = postgres_housing
    box.store.create_task(TaskCreate(title="PG-PRIVATE-B1-HINT", property_id=box.property.id))
    client, accounts, tokens = client_for(box.store, box.p.id, monkeypatch)
    original = router.dashboard_summary

    def revoke_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        with scope_context(None):
            if change == "session":
                auth.revoke_token(tokens.access_token)
            else:
                values = {"role": {"role": "verwalter"}, "grants": {"portfolio_access": "selected", "portfolio_ids": []},
                          "activation": {"is_active": False}}[change]
                accounts.update("dashboard-reader", values)
        return result

    monkeypatch.setattr(router, "dashboard_summary", revoke_after_read)
    with client:
        response = client.get("/api/v1/dashboard/stats", headers={"Authorization": "Bearer " + tokens.access_token})
    assert response.status_code in {401, 403}, response.text
    assert "PG-PRIVATE-B1-HINT" not in response.text
    assert "notification_count" not in response.text
