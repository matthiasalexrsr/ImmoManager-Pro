"""The public API catalog must have one method, one endpoint, one operation ID.

The runtime-safe admin wrappers own their public routes; legacy helper
functions stay available for internal calls but must not register duplicates.
"""
from collections import Counter

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app import app
from backend.routers import admin, admin_runtime
from backend.routing import build_api_v1


def test_no_duplicate_api_paths_or_operation_ids_and_runtime_admin_routes_are_authoritative():
    routes = [route for route in build_api_v1().routes if isinstance(route, APIRoute)]
    operations = [(method, route.path, route.unique_id)
                  for route in routes for method in route.methods if method not in {"OPTIONS", "HEAD"}]
    names = Counter(identifier for _method, _path, identifier in operations)
    paths = Counter((method, path) for method, path, _id in operations)
    assert not {key: count for key, count in names.items() if count > 1}, "Ambiguous OpenAPI operation identifiers"
    assert not {key: count for key, count in paths.items() if count > 1}, "Ambiguous HTTP method/path registrations"

    for suffix, endpoint in (
        ("/system-status", admin_runtime.system_status),
        ("/database-info", admin_runtime.get_database_info),
    ):
        matches = [(method, route) for route in routes
                   for method in route.methods if method == "GET" and route.path == "/api/v1/admin" + suffix]
        assert len(matches) == 1
        assert matches[0][1].endpoint is endpoint
    assert all(route.endpoint not in (admin.system_status, admin.get_database_info) for route in routes)


def test_actual_generated_openapi_ids_are_unique_and_anonymous_admin_stays_denied():
    document = app.openapi()
    identifiers = [operation["operationId"] for methods in document["paths"].values()
                   for verb, operation in methods.items() if verb.lower() in
                   {"get", "put", "post", "patch", "delete"}]
    assert len(identifiers) == len(set(identifiers))
    with TestClient(app) as client:
        for path in ("/api/v1/admin/system-status", "/api/v1/admin/database-info"):
            response = client.get(path)
            assert response.status_code in (401, 403)
