"""End-to-end integration tests using FastAPI TestClient.

These tests exercise complete user flows through the HTTP API,
chaining multiple requests to verify realistic usage scenarios.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean():
    """Clear store and users before each test."""
    for attr in [
        "portfolios", "properties", "units", "tenants", "contracts",
        "accounts", "bookings", "categories", "receivables", "invoices",
        "maintenance_cases", "documents", "tasks", "calendar_events",
        "listings", "listing_photos", "leads", "viewing_appointments",
        "billing_periods", "allocation_keys", "cost_items",
        "utility_statements", "deposits", "notifications",
        "notification_templates", "tax_rates", "rent_adjustments",
        "handover_protocols", "meter_readings", "budgets",
        "escalation_rules", "change_history",
    ]:
        collection = getattr(store, attr, None)
        if collection is not None and isinstance(collection, dict):
            collection.clear()
    clear_users()
    yield
    clear_users()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    user = register_user("testuser", "test@example.com", "Test User", "Secret123", "eigentuemer")
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helper to create prerequisite entities via the API
# ---------------------------------------------------------------------------


def _create_portfolio(client, headers, name="Test Portfolio"):
    """Create a portfolio and return its JSON."""
    resp = client.post(
        "/api/v1/portfolios",
        json={"name": name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_property(client, headers, portfolio_id, name="Musterhaus"):
    """Create a property and return its JSON."""
    resp = client.post(
        "/api/v1/properties",
        json={
            "portfolio_id": portfolio_id,
            "name": name,
            "property_type": "residential",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_unit(client, headers, property_id, label="Wohnung 1"):
    """Create a unit and return its JSON."""
    resp = client.post(
        "/api/v1/units",
        json={
            "property_id": property_id,
            "label": label,
            "unit_type": "apartment",
            "cold_rent": 750.0,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_tenant(client, headers, name="Max Mustermann"):
    """Create a tenant and return its JSON."""
    resp = client.post(
        "/api/v1/tenants",
        json={"full_name": name, "email": "max@example.com"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Property Management Flow
# ---------------------------------------------------------------------------


class TestPropertyManagementFlow:
    """Create portfolio -> property -> unit -> update unit -> delete property -> verify cascade."""

    def test_full_property_lifecycle(self, client, auth_headers):
        # Step 1: Create a portfolio
        portfolio = _create_portfolio(client, auth_headers, "Immobilien GmbH")
        portfolio_id = portfolio["id"]
        assert portfolio["name"] == "Immobilien GmbH"

        # Step 2: Create a property under that portfolio
        prop = _create_property(client, auth_headers, portfolio_id, "Berliner Str. 42")
        property_id = prop["id"]
        assert prop["portfolio_id"] == portfolio_id
        assert prop["name"] == "Berliner Str. 42"

        # Step 3: Create a unit under that property
        unit = _create_unit(client, auth_headers, property_id, "EG Links")
        unit_id = unit["id"]
        assert unit["property_id"] == property_id
        assert unit["label"] == "EG Links"

        # Step 4: PATCH the unit to update its rent
        patch_resp = client.patch(
            f"/api/v1/units/{unit_id}",
            json={"cold_rent": 850.0, "status": "rented"},
            headers=auth_headers,
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["cold_rent"] == 850.0
        assert patched["status"] == "rented"

        # Step 5: Delete the property (should cascade-delete the unit)
        del_resp = client.delete(
            f"/api/v1/properties/{property_id}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

        # Step 6: Verify the unit was cascade-deleted
        units_resp = client.get("/api/v1/units", headers=auth_headers)
        assert units_resp.status_code == 200
        remaining_units = units_resp.json()
        assert len(remaining_units) == 0

        # Verify the property is gone too
        get_resp = client.get(
            f"/api/v1/properties/{property_id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Tenant-Contract Flow
# ---------------------------------------------------------------------------


class TestTenantContractFlow:
    """Create tenant -> contract -> receivable -> verify listing."""

    def test_tenant_contract_receivable_chain(self, client, auth_headers):
        # Prerequisites: portfolio + property + unit
        portfolio = _create_portfolio(client, auth_headers)
        prop = _create_property(client, auth_headers, portfolio["id"])
        unit = _create_unit(client, auth_headers, prop["id"])

        # Step 1: Create a tenant
        tenant = _create_tenant(client, auth_headers, "Anna Schmidt")
        tenant_id = tenant["id"]
        assert tenant["full_name"] == "Anna Schmidt"

        # Step 2: Create a contract linking tenant, property, and unit
        contract_resp = client.post(
            "/api/v1/contracts",
            json={
                "contract_number": "V-2025-001",
                "property_id": prop["id"],
                "unit_id": unit["id"],
                "tenant_id": tenant_id,
                "start_date": "2025-01-01",
                "status": "active",
            },
            headers=auth_headers,
        )
        assert contract_resp.status_code == 201
        contract = contract_resp.json()
        contract_id = contract["id"]
        assert contract["contract_number"] == "V-2025-001"

        # Step 3: Create a receivable for that contract
        recv_resp = client.post(
            "/api/v1/receivables",
            json={
                "contract_id": contract_id,
                "due_date": "2025-02-01",
                "amount_due": 750.0,
                "status": "open",
            },
            headers=auth_headers,
        )
        assert recv_resp.status_code == 201
        receivable = recv_resp.json()
        assert receivable["contract_id"] == contract_id
        assert receivable["amount_due"] == 750.0

        # Step 4: List receivables and verify the one we created is there
        list_resp = client.get(
            "/api/v1/receivables",
            params={"contract_id": contract_id},
            headers=auth_headers,
        )
        assert list_resp.status_code == 200
        receivables = list_resp.json()
        assert len(receivables) == 1
        assert receivables[0]["id"] == receivable["id"]


# ---------------------------------------------------------------------------
# 3. Maintenance Workflow
# ---------------------------------------------------------------------------


class TestMaintenanceWorkflow:
    """Create property -> maintenance case -> update status -> list filtered."""

    def test_maintenance_lifecycle(self, client, auth_headers):
        # Prerequisites
        portfolio = _create_portfolio(client, auth_headers)
        prop = _create_property(client, auth_headers, portfolio["id"])

        # Step 1: Create a maintenance case
        case_resp = client.post(
            "/api/v1/maintenance",
            json={
                "property_id": prop["id"],
                "title": "Heizungsausfall",
                "description": "Heizung im EG funktioniert nicht",
                "priority": "high",
                "status": "open",
                "category": "heating",
                "estimated_cost": 2500.0,
            },
            headers=auth_headers,
        )
        assert case_resp.status_code == 201
        case = case_resp.json()
        case_id = case["id"]
        assert case["title"] == "Heizungsausfall"
        assert case["status"] == "open"

        # Step 2: PATCH to update status to in_progress
        patch_resp = client.patch(
            f"/api/v1/maintenance/{case_id}",
            json={"status": "in_progress", "assignee": "Techniker A"},
            headers=auth_headers,
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["status"] == "in_progress"
        assert patched["assignee"] == "Techniker A"

        # Step 3: Filter maintenance cases by status=in_progress
        filtered_resp = client.get(
            "/api/v1/maintenance",
            params={"status": "in_progress"},
            headers=auth_headers,
        )
        assert filtered_resp.status_code == 200
        filtered = filtered_resp.json()
        assert len(filtered) == 1
        assert filtered[0]["id"] == case_id
        assert filtered[0]["status"] == "in_progress"

        # Step 4: Verify filtering by status=open returns empty
        open_resp = client.get(
            "/api/v1/maintenance",
            params={"status": "open"},
            headers=auth_headers,
        )
        assert open_resp.status_code == 200
        assert len(open_resp.json()) == 0


# ---------------------------------------------------------------------------
# 4. Financial Flow
# ---------------------------------------------------------------------------


class TestFinancialFlow:
    """Create account -> booking -> list -> report summary."""

    def test_financial_lifecycle(self, client, auth_headers):
        # Prerequisite: portfolio
        portfolio = _create_portfolio(client, auth_headers, "Finanzen Portfolio")

        # Step 1: Create a bank account
        acc_resp = client.post(
            "/api/v1/accounts",
            json={
                "portfolio_id": portfolio["id"],
                "name": "Hausverwaltung Konto",
                "account_type": "bank",
                "bank_name": "Deutsche Bank",
                "opening_balance": 10000.0,
                "balance": 10000.0,
            },
            headers=auth_headers,
        )
        assert acc_resp.status_code == 201
        account = acc_resp.json()
        account_id = account["id"]
        assert account["name"] == "Hausverwaltung Konto"

        # Step 2: Create a booking (income)
        booking_resp = client.post(
            "/api/v1/bookings",
            json={
                "account_id": account_id,
                "booking_date": "2025-01-15",
                "amount": 750.0,
                "payment_text": "Miete Januar Wohnung 1",
            },
            headers=auth_headers,
        )
        assert booking_resp.status_code == 201
        booking = booking_resp.json()
        assert booking["amount"] == 750.0

        # Step 3: Create a second booking (expense)
        expense_resp = client.post(
            "/api/v1/bookings",
            json={
                "account_id": account_id,
                "booking_date": "2025-01-20",
                "amount": -200.0,
                "payment_text": "Reparatur Heizung",
            },
            headers=auth_headers,
        )
        assert expense_resp.status_code == 201

        # Step 4: List bookings for the account
        list_resp = client.get(
            "/api/v1/bookings",
            params={"account_id": account_id},
            headers=auth_headers,
        )
        assert list_resp.status_code == 200
        bookings = list_resp.json()
        assert len(bookings) == 2

        # Step 5: Fetch the summary report
        summary_resp = client.get(
            "/api/v1/reports/summary",
            headers=auth_headers,
        )
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert summary["finance"]["bookingsTotal"] == 550.0  # 750 + (-200)
        assert summary["totals"]["properties"] == 0  # no properties created


# ---------------------------------------------------------------------------
# 5. Auth + User Management Flow
# ---------------------------------------------------------------------------


class TestAuthUserManagementFlow:
    """Register -> login -> get me -> create second user -> list users -> delete user."""

    def test_auth_full_flow(self, client):
        # Step 1: Register a user (eigentuemer role via self-register gets capped to readonly)
        reg_resp = client.post(
            "/api/v1/auth/register",
            json={
                "username": "admin1",
                "email": "admin1@example.com",
                "full_name": "Admin Eins",
                "password": "Secret123",
                "role": "readonly",
            },
        )
        assert reg_resp.status_code == 201
        user1 = reg_resp.json()
        user1_id = user1["id"]
        assert user1["username"] == "admin1"

        # Step 2: Login with the registered user
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin1", "password": "Secret123"},
        )
        assert login_resp.status_code == 200
        tokens = login_resp.json()
        assert "access_token" in tokens
        assert tokens["token_type"] == "bearer"

        # Step 3: Get current user profile using the token
        me_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        me_resp = client.get("/api/v1/auth/me", headers=me_headers)
        assert me_resp.status_code == 200
        me = me_resp.json()
        assert me["username"] == "admin1"
        assert me["email"] == "admin1@example.com"

        # Step 4: Register a second user
        reg2_resp = client.post(
            "/api/v1/auth/register",
            json={
                "username": "user2",
                "email": "user2@example.com",
                "full_name": "User Zwei",
                "password": "Secret456",
                "role": "readonly",
            },
        )
        assert reg2_resp.status_code == 201
        user2 = reg2_resp.json()
        user2_id = user2["id"]

        # Step 5: List users (requires eigentuemer or verwalter role)
        # The self-registered user is readonly, so we create an eigentuemer via the auth module
        owner = register_user("owner", "owner@example.com", "Owner", "Secret789", "eigentuemer")
        owner_token = create_access_token(owner.id)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        users_resp = client.get("/api/v1/auth/users", headers=owner_headers)
        assert users_resp.status_code == 200
        users = users_resp.json()
        # Should have at least admin1, user2, and owner
        usernames = {u["username"] for u in users}
        assert "admin1" in usernames
        assert "user2" in usernames
        assert "owner" in usernames

        # Step 6: Delete user2 (only eigentuemer can delete)
        del_resp = client.delete(
            f"/api/v1/auth/users/{user2_id}",
            headers=owner_headers,
        )
        assert del_resp.status_code == 204

        # Verify user2 is gone
        users_after = client.get("/api/v1/auth/users", headers=owner_headers)
        usernames_after = {u["username"] for u in users_after.json()}
        assert "user2" not in usernames_after


# ---------------------------------------------------------------------------
# 6. Tax Rate CRUD via HTTP
# ---------------------------------------------------------------------------


class TestTaxRateCRUD:
    """POST, GET, PATCH, DELETE /api/v1/tax-rates."""

    def test_tax_rate_full_crud(self, client, auth_headers):
        # Create
        create_resp = client.post(
            "/api/v1/tax-rates",
            json={
                "name": "Regelsteuersatz",
                "rate": 19.0,
                "description": "Standard-MwSt.",
                "is_default": True,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        tax_rate = create_resp.json()
        tax_id = tax_rate["id"]
        assert tax_rate["name"] == "Regelsteuersatz"
        assert tax_rate["rate"] == 19.0

        # Read (GET by id)
        get_resp = client.get(f"/api/v1/tax-rates/{tax_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == tax_id

        # List
        list_resp = client.get("/api/v1/tax-rates", headers=auth_headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        # Patch (update rate to reduced)
        patch_resp = client.patch(
            f"/api/v1/tax-rates/{tax_id}",
            json={"rate": 7.0, "name": "Ermaessigt"},
            headers=auth_headers,
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["rate"] == 7.0
        assert patched["name"] == "Ermaessigt"

        # Delete
        del_resp = client.delete(f"/api/v1/tax-rates/{tax_id}", headers=auth_headers)
        assert del_resp.status_code == 204

        # Verify deletion
        get_deleted = client.get(f"/api/v1/tax-rates/{tax_id}", headers=auth_headers)
        assert get_deleted.status_code == 404


# ---------------------------------------------------------------------------
# 7. Budget Analysis via HTTP
# ---------------------------------------------------------------------------


class TestBudgetAnalysis:
    """Create budgets then GET /api/v1/budgets/analysis."""

    def test_budget_analysis_endpoint(self, client, auth_headers):
        # Create a property first (budget requires property_id)
        portfolio = _create_portfolio(client, auth_headers)
        prop = _create_property(client, auth_headers, portfolio["id"])
        property_id = prop["id"]

        # Create two budgets for the property
        budget1_resp = client.post(
            "/api/v1/budgets",
            json={
                "property_id": property_id,
                "year": 2025,
                "category": "maintenance",
                "planned_amount": 5000.0,
                "actual_amount": 3200.0,
            },
            headers=auth_headers,
        )
        assert budget1_resp.status_code == 201

        budget2_resp = client.post(
            "/api/v1/budgets",
            json={
                "property_id": property_id,
                "year": 2025,
                "category": "operating_costs",
                "planned_amount": 8000.0,
                "actual_amount": 7500.0,
            },
            headers=auth_headers,
        )
        assert budget2_resp.status_code == 201

        # Fetch the budget analysis
        analysis_resp = client.get(
            "/api/v1/budgets/analysis",
            params={"property_id": property_id, "year": 2025},
            headers=auth_headers,
        )
        assert analysis_resp.status_code == 200
        analysis = analysis_resp.json()

        # total_planned = 5000 + 8000 = 13000
        assert analysis["total_planned"] == 13000.0
        # total_actual = 3200 + 7500 = 10700
        assert analysis["total_actual"] == 10700.0
        # deviation = 10700 - 13000 = -2300
        assert analysis["total_deviation"] == -2300.0
        # utilization = 10700/13000 * 100
        assert abs(analysis["utilization_percent"] - (10700 / 13000 * 100)) < 0.1
        # by_category should have two entries
        assert len(analysis["by_category"]) == 2


# ---------------------------------------------------------------------------
# 8. Escalation Run via HTTP
# ---------------------------------------------------------------------------


class TestEscalationRun:
    """Create rule + overdue task, POST /api/v1/escalation/run."""

    def test_escalation_generates_notifications(self, client, auth_headers):
        # Step 1: Create an escalation rule for overdue tasks
        rule_resp = client.post(
            "/api/v1/escalation/rules",
            json={
                "name": "Overdue Task Alert",
                "entity_type": "task",
                "condition_field": "due_date",
                "days_overdue": 3,
                "action": "notify",
                "notification_severity": "warning",
                "is_active": True,
            },
            headers=auth_headers,
        )
        assert rule_resp.status_code == 201

        # Step 2: Create a task that is overdue (due_date 10 days ago)
        overdue_date = (date.today() - timedelta(days=10)).isoformat()
        task_resp = client.post(
            "/api/v1/tasks",
            json={
                "title": "Rauchmelder pruefen",
                "due_date": overdue_date,
                "status": "open",
                "priority": "high",
            },
            headers=auth_headers,
        )
        assert task_resp.status_code == 201

        # Step 3: Create a task that is NOT overdue (due tomorrow)
        future_date = (date.today() + timedelta(days=1)).isoformat()
        client.post(
            "/api/v1/tasks",
            json={
                "title": "Garten pflegen",
                "due_date": future_date,
                "status": "open",
            },
            headers=auth_headers,
        )

        # Step 4: Run escalation
        run_resp = client.post(
            "/api/v1/escalation/run",
            headers=auth_headers,
        )
        assert run_resp.status_code == 200
        result = run_resp.json()
        assert result["rules_checked"] == 1
        assert result["notifications_generated"] == 1

        # Step 5: Verify notification was created
        notif_resp = client.get("/api/v1/notifications", headers=auth_headers)
        assert notif_resp.status_code == 200
        notifications = notif_resp.json()
        assert len(notifications) == 1
        assert "Rauchmelder pruefen" in notifications[0]["title"]
        assert notifications[0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# 9. Notification Lifecycle
# ---------------------------------------------------------------------------


class TestNotificationLifecycle:
    """POST notification -> GET -> mark read -> verify status change."""

    def test_notification_create_read_lifecycle(self, client, auth_headers):
        # Step 1: Create a notification
        create_resp = client.post(
            "/api/v1/notifications",
            json={
                "notification_type": "general",
                "title": "Willkommen",
                "content": "Willkommen bei ImmoManager Pro!",
                "severity": "info",
                "status": "unread",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        notif = create_resp.json()
        notif_id = notif["id"]
        assert notif["status"] == "unread"
        assert notif["read_at"] is None

        # Step 2: GET the notification
        get_resp = client.get(
            f"/api/v1/notifications/{notif_id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Willkommen"

        # Step 3: Mark as read via POST /{id}/read
        read_resp = client.post(
            f"/api/v1/notifications/{notif_id}/read",
            headers=auth_headers,
        )
        assert read_resp.status_code == 200
        read_notif = read_resp.json()
        assert read_notif["status"] == "read"
        assert read_notif["read_at"] is not None

        # Step 4: Verify via GET that the status persisted
        verify_resp = client.get(
            f"/api/v1/notifications/{notif_id}",
            headers=auth_headers,
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["status"] == "read"

        # Step 5: Filter by status=unread should return empty now
        unread_resp = client.get(
            "/api/v1/notifications",
            params={"status": "unread"},
            headers=auth_headers,
        )
        assert unread_resp.status_code == 200
        assert len(unread_resp.json()) == 0


# ---------------------------------------------------------------------------
# 10. Pagination Test
# ---------------------------------------------------------------------------


class TestPagination:
    """Create 5 items, verify skip/limit works on list endpoint."""

    def test_pagination_on_portfolios(self, client, auth_headers):
        # Create 5 portfolios
        created_ids = []
        for i in range(5):
            resp = client.post(
                "/api/v1/portfolios",
                json={"name": f"Portfolio {i + 1}"},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            created_ids.append(resp.json()["id"])

        # List all (default limit=100)
        all_resp = client.get("/api/v1/portfolios", headers=auth_headers)
        assert all_resp.status_code == 200
        assert len(all_resp.json()) == 5

        # Limit to 2
        page1 = client.get(
            "/api/v1/portfolios",
            params={"skip": 0, "limit": 2},
            headers=auth_headers,
        )
        assert page1.status_code == 200
        page1_data = page1.json()
        assert len(page1_data) == 2

        # Skip 2, limit 2 (second page)
        page2 = client.get(
            "/api/v1/portfolios",
            params={"skip": 2, "limit": 2},
            headers=auth_headers,
        )
        assert page2.status_code == 200
        page2_data = page2.json()
        assert len(page2_data) == 2

        # Pages should not overlap
        page1_ids = {p["id"] for p in page1_data}
        page2_ids = {p["id"] for p in page2_data}
        assert page1_ids.isdisjoint(page2_ids)

        # Skip 4, limit 2 (last page, only 1 item)
        page3 = client.get(
            "/api/v1/portfolios",
            params={"skip": 4, "limit": 2},
            headers=auth_headers,
        )
        assert page3.status_code == 200
        page3_data = page3.json()
        assert len(page3_data) == 1

        # Skip past all items
        empty_page = client.get(
            "/api/v1/portfolios",
            params={"skip": 10, "limit": 2},
            headers=auth_headers,
        )
        assert empty_page.status_code == 200
        assert len(empty_page.json()) == 0


# ---------------------------------------------------------------------------
# 11. Unauthenticated Access Denied
# ---------------------------------------------------------------------------


class TestUnauthenticatedAccessDenied:
    """Verify that protected endpoints reject unauthenticated requests."""

    def test_protected_endpoints_require_auth(self, client):
        # No auth header - should be 401/403
        endpoints = [
            ("GET", "/api/v1/portfolios"),
            ("POST", "/api/v1/portfolios"),
            ("GET", "/api/v1/properties"),
            ("GET", "/api/v1/units"),
            ("GET", "/api/v1/tenants"),
            ("GET", "/api/v1/bookings"),
            ("GET", "/api/v1/reports/summary"),
        ]
        for method, path in endpoints:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path, json={})
            assert resp.status_code in (401, 403), (
                f"{method} {path} returned {resp.status_code}, expected 401 or 403"
            )


# ---------------------------------------------------------------------------
# 12. Cross-entity Filter Consistency
# ---------------------------------------------------------------------------


class TestCrossEntityFilterConsistency:
    """Create data across entities and verify filter parameters work correctly."""

    def test_filter_by_property_id(self, client, auth_headers):
        # Create two portfolios with one property each
        p1 = _create_portfolio(client, auth_headers, "Portfolio A")
        p2 = _create_portfolio(client, auth_headers, "Portfolio B")

        prop1 = _create_property(client, auth_headers, p1["id"], "Haus A")
        prop2 = _create_property(client, auth_headers, p2["id"], "Haus B")

        # Create maintenance cases for each property
        for prop_id, title in [(prop1["id"], "Dach reparieren"), (prop2["id"], "Fenster tauschen")]:
            client.post(
                "/api/v1/maintenance",
                json={
                    "property_id": prop_id,
                    "title": title,
                    "status": "open",
                },
                headers=auth_headers,
            )

        # Filter maintenance by property_id for prop1
        resp1 = client.get(
            "/api/v1/maintenance",
            params={"property_id": prop1["id"]},
            headers=auth_headers,
        )
        assert resp1.status_code == 200
        cases1 = resp1.json()
        assert len(cases1) == 1
        assert cases1[0]["title"] == "Dach reparieren"

        # Filter maintenance by property_id for prop2
        resp2 = client.get(
            "/api/v1/maintenance",
            params={"property_id": prop2["id"]},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        cases2 = resp2.json()
        assert len(cases2) == 1
        assert cases2[0]["title"] == "Fenster tauschen"

        # Filter properties by portfolio_id
        props_resp = client.get(
            "/api/v1/properties",
            params={"portfolio_id": p1["id"]},
            headers=auth_headers,
        )
        assert props_resp.status_code == 200
        props = props_resp.json()
        assert len(props) == 1
        assert props[0]["name"] == "Haus A"
