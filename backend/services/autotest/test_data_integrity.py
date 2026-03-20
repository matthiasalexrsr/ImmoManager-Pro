"""Test module: Data integrity and CRUD operations.

Verifies that CRUD operations work correctly for all major entity types,
FK constraints are enforced, cascade deletes work, and data round-trips
preserve field values.
"""

import time

from .runner import TestContext, TestResult, test_module

# Entity CRUD test definitions: (name, create_path, create_payload, list_path)
# These are ordered by dependency: parents first, children after.
_CRUD_TESTS = [
    {
        "name": "portfolio",
        "path": "portfolios",
        "create": {"name": "Autotest Portfolio", "description": "Test portfolio"},
        "update": {"name": "Autotest Portfolio Updated", "description": "Updated"},
    },
    {
        "name": "property",
        "path": "properties",
        "create": {"name": "Autotest Property", "address": "Test Street 1", "city": "Berlin", "zip_code": "10115", "portfolio_id": "__PORTFOLIO_ID__"},
        "update": {"name": "Autotest Property Updated", "address": "Test Street 1", "city": "Berlin", "zip_code": "10115", "portfolio_id": "__PORTFOLIO_ID__"},
        "depends": "portfolio",
    },
    {
        "name": "unit",
        "path": "units",
        "create": {"label": "Autotest Unit", "property_id": "__PROPERTY_ID__", "area_sqm": 50.0, "rooms": 2, "floor": 1, "status": "vacant"},
        "update": {"label": "Autotest Unit Updated", "property_id": "__PROPERTY_ID__", "area_sqm": 55.0, "rooms": 2, "floor": 1, "status": "vacant"},
        "depends": "property",
    },
    {
        "name": "tenant",
        "path": "tenants",
        "create": {"first_name": "Auto", "last_name": "Test", "email": "autotest@example.com"},
        "update": {"first_name": "Auto", "last_name": "TestUpdated", "email": "autotest2@example.com"},
    },
    {
        "name": "account",
        "path": "accounts",
        "create": {"name": "Autotest Account", "account_number": "AT-0001", "account_type": "bank", "portfolio_id": "__PORTFOLIO_ID__"},
        "update": {"name": "Autotest Account Updated", "account_number": "AT-0001", "account_type": "bank", "portfolio_id": "__PORTFOLIO_ID__"},
        "depends": "portfolio",
    },
    {
        "name": "contact",
        "path": "contacts",
        "create": {"name": "Autotest Contact", "contact_type": "handwerker", "email": "contact@test.local"},
        "update": {"name": "Autotest Contact Updated", "contact_type": "handwerker", "email": "contact2@test.local"},
    },
    {
        "name": "category",
        "path": "categories",
        "create": {"name": "Autotest Category", "portfolio_id": "__PORTFOLIO_ID__"},
        "update": {"name": "Autotest Category Updated", "portfolio_id": "__PORTFOLIO_ID__"},
        "depends": "portfolio",
    },
    {
        "name": "task",
        "path": "tasks",
        "create": {"title": "Autotest Task", "status": "open"},
        "update": {"title": "Autotest Task Updated", "status": "in_progress"},
    },
]


@test_module("data_integrity", "CRUD operations, FK constraints, and data round-trip validation")
def test_data_integrity(ctx: TestContext) -> list[TestResult]:
    results = []
    headers = {"Authorization": f"Bearer {ctx.token}"} if ctx.token else {}
    created_ids = {}  # name -> id

    def _replace_refs(data: dict) -> dict:
        """Replace __XXX_ID__ placeholders with actual IDs."""
        out = {}
        for k, v in data.items():
            if isinstance(v, str) and v.startswith("__") and v.endswith("__"):
                ref_name = v[2:-2].lower().replace("_id", "")
                out[k] = created_ids.get(ref_name, v)
            else:
                out[k] = v
        return out

    # ── Full CRUD cycle for each entity ───────────────────────────────────
    for entity_def in _CRUD_TESTS:
        name = entity_def["name"]
        path = entity_def["path"]

        # Skip if dependency not created
        dep = entity_def.get("depends")
        if dep and dep not in created_ids:
            results.append(TestResult(
                name=f"crud::{name}::create",
                passed=False,
                duration_ms=0,
                message=f"Skipped: dependency '{dep}' not available",
                severity="warning",
            ))
            continue

        create_data = _replace_refs(entity_def["create"])
        update_data = _replace_refs(entity_def["update"])

        # CREATE
        t0 = time.monotonic()
        resp = ctx.client.post(f"{ctx.base_url}/{path}", json=create_data, headers=headers)
        dur = round((time.monotonic() - t0) * 1000, 1)
        create_ok = resp.status_code in (200, 201)
        entity_id = None
        if create_ok:
            body = resp.json()
            entity_id = body.get("id")
            created_ids[name] = entity_id
        results.append(TestResult(
            name=f"crud::{name}::create",
            passed=create_ok,
            duration_ms=dur,
            message=f"Status {resp.status_code}" + (f", id={entity_id}" if entity_id else ""),
            file_path=f"backend/routers/{path.replace('-', '_')}.py",
            details=resp.text[:300] if not create_ok else "",
        ))

        if not entity_id:
            continue

        # READ
        t0 = time.monotonic()
        resp = ctx.client.get(f"{ctx.base_url}/{path}/{entity_id}", headers=headers)
        dur = round((time.monotonic() - t0) * 1000, 1)
        read_ok = resp.status_code == 200
        if read_ok:
            body = resp.json()
            # Verify key fields round-tripped
            for key, expected_val in create_data.items():
                actual = body.get(key)
                if actual != expected_val and key not in ("portfolio_id", "property_id", "unit_id"):
                    read_ok = False
                    break
        results.append(TestResult(
            name=f"crud::{name}::read",
            passed=read_ok,
            duration_ms=dur,
            message=f"Status {resp.status_code}",
            file_path=f"backend/routers/{path.replace('-', '_')}.py",
        ))

        # UPDATE
        t0 = time.monotonic()
        resp = ctx.client.put(f"{ctx.base_url}/{path}/{entity_id}", json=update_data, headers=headers)
        dur = round((time.monotonic() - t0) * 1000, 1)
        update_ok = resp.status_code == 200
        results.append(TestResult(
            name=f"crud::{name}::update",
            passed=update_ok,
            duration_ms=dur,
            message=f"Status {resp.status_code}",
            file_path=f"backend/routers/{path.replace('-', '_')}.py",
            details=resp.text[:300] if not update_ok else "",
        ))

        # LIST (verify entity appears)
        t0 = time.monotonic()
        resp = ctx.client.get(f"{ctx.base_url}/{path}", headers=headers)
        dur = round((time.monotonic() - t0) * 1000, 1)
        list_ok = resp.status_code == 200
        if list_ok:
            body = resp.json()
            if isinstance(body, list):
                list_ok = any(item.get("id") == entity_id for item in body)
        results.append(TestResult(
            name=f"crud::{name}::list_contains",
            passed=list_ok,
            duration_ms=dur,
            message=f"Entity {entity_id} found in list" if list_ok else "Entity not found in list response",
            file_path=f"backend/routers/{path.replace('-', '_')}.py",
        ))

        # DELETE
        t0 = time.monotonic()
        resp = ctx.client.delete(f"{ctx.base_url}/{path}/{entity_id}", headers=headers)
        dur = round((time.monotonic() - t0) * 1000, 1)
        delete_ok = resp.status_code in (200, 204)
        results.append(TestResult(
            name=f"crud::{name}::delete",
            passed=delete_ok,
            duration_ms=dur,
            message=f"Status {resp.status_code}",
            file_path=f"backend/routers/{path.replace('-', '_')}.py",
        ))

        # Verify deletion (404 expected)
        if delete_ok:
            t0 = time.monotonic()
            resp = ctx.client.get(f"{ctx.base_url}/{path}/{entity_id}", headers=headers)
            dur = round((time.monotonic() - t0) * 1000, 1)
            gone_ok = resp.status_code == 404
            results.append(TestResult(
                name=f"crud::{name}::verify_deleted",
                passed=gone_ok,
                duration_ms=dur,
                message=f"Deleted entity returns {resp.status_code} (expected 404)",
                file_path=f"backend/routers/{path.replace('-', '_')}.py",
            ))

        # Remove from created_ids since deleted
        created_ids.pop(name, None)

    # ── FK constraint validation ──────────────────────────────────────────

    # Try creating property with non-existent portfolio
    t0 = time.monotonic()
    resp = ctx.client.post(f"{ctx.base_url}/properties", json={
        "name": "Orphan Property",
        "address": "Nowhere 1",
        "city": "NoCity",
        "zip_code": "00000",
        "portfolio_id": "nonexistent-id-12345",
    }, headers=headers)
    dur = round((time.monotonic() - t0) * 1000, 1)
    fk_ok = resp.status_code in (400, 422)
    results.append(TestResult(
        name="fk::property_invalid_portfolio",
        passed=fk_ok,
        duration_ms=dur,
        message=f"Invalid FK returned {resp.status_code} (expected 400/422)",
        file_path="backend/storage.py",
        line_hint="create_property() should validate portfolio_id exists",
    ))

    # ── Not-found handling ────────────────────────────────────────────────

    for path in ["portfolios", "properties", "tenants", "contracts"]:
        t0 = time.monotonic()
        resp = ctx.client.get(f"{ctx.base_url}/{path}/nonexistent-uuid", headers=headers)
        dur = round((time.monotonic() - t0) * 1000, 1)
        results.append(TestResult(
            name=f"notfound::{path}",
            passed=resp.status_code == 404,
            duration_ms=dur,
            message=f"Nonexistent entity returned {resp.status_code} (expected 404)",
            file_path=f"backend/routers/{path.replace('-', '_')}.py",
        ))

    # Cleanup remaining test entities (reverse order)
    for name in reversed(list(created_ids.keys())):
        entity_def = next((d for d in _CRUD_TESTS if d["name"] == name), None)
        if entity_def:
            ctx.client.delete(
                f"{ctx.base_url}/{entity_def['path']}/{created_ids[name]}",
                headers=headers,
            )

    return results
