"""Local plugins cannot expose unauthenticated or partially started routes."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.auth import UserRead
from backend.plugins import discover_plugins, start_plugins, stop_plugins
from backend.plugins.base import Plugin


class ExamplePlugin(Plugin):
    name = "example"
    version = "1.0.0"

    def __init__(self, fail=False):
        self.fail = fail
        self.stopped = 0

    def register_routes(self, app, prefix):
        @app.get("/info")
        def info():
            return {"ready": True}

        @app.post("/change")
        def change():
            return {"changed": True}

        nested = FastAPI()

        @nested.get("/info")
        def nested_info():
            return {"nested": True}

        app.mount("/nested", nested)

    def on_startup(self):
        if self.fail:
            raise RuntimeError("injected startup failure")

    def on_shutdown(self):
        self.stopped += 1


@pytest.fixture
def plugin_app(monkeypatch):
    async def authenticate(credentials):
        if credentials is None:
            return None
        if credentials.credentials == "invalid":
            raise HTTPException(401, "Invalid token")
        if credentials.credentials == "inactive":
            raise HTTPException(403, "Inactive user")
        return UserRead(id="synthetic", username="test", email="test@example.com", full_name="Test", role=credentials.credentials, is_active=True)

    monkeypatch.setattr("backend.plugins.runtime.get_current_user", authenticate)
    app = FastAPI()

    @app.get("/{full_path:path}")
    def spa(full_path):
        return {"spa": True}

    plugin = ExamplePlugin()
    start_plugins(app, [plugin])
    return app, plugin


def test_plugin_route_auth_precedes_frontend_and_protects_nested_mounts(plugin_app):
    app, plugin = plugin_app
    client = TestClient(app)
    for path in ("/api/v1/plugins/example/info", "/api/v1/plugins/example/nested/info"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer inactive"}).status_code == 403
        assert client.get(path, headers={"Authorization": "Bearer eigentuemer"}).status_code == 200
    assert plugin.to_dict()["status"] == "active"


def test_readonly_can_read_but_cannot_mutate_plugin(plugin_app):
    app, _ = plugin_app
    client = TestClient(app)
    headers = {"Authorization": "Bearer readonly"}
    assert client.get("/api/v1/plugins/example/info", headers=headers).json() == {"ready": True}
    assert client.post("/api/v1/plugins/example/change", headers=headers).status_code == 403
    assert client.post("/api/v1/plugins/example/change", headers={"Authorization": "Bearer verwalter"}).status_code == 200


def test_failed_startup_publishes_no_routes_and_does_not_shutdown_twice():
    app = FastAPI()
    plugin = ExamplePlugin(fail=True)
    start_plugins(app, [plugin])
    assert plugin.to_dict()["status"] == "failed"
    assert TestClient(app).get("/api/v1/plugins/example/info").status_code == 404
    assert plugin.stopped == 1
    stop_plugins(app, [plugin])
    assert plugin.stopped == 1


def test_shutdown_removes_owned_mount_and_allows_clean_restart(plugin_app):
    app, plugin = plugin_app
    stop_plugins(app, [plugin])
    assert plugin.stopped == 1
    assert plugin.to_dict()["status"] == "stopped"
    assert not any(getattr(route, "name", "") == "local-plugin-example" for route in app.routes)
    start_plugins(app, [plugin])
    assert sum(getattr(route, "name", "") == "local-plugin-example" for route in app.routes) == 1


def test_discovery_validates_names_and_avoids_global_package_collisions(tmp_path):
    source = '''from backend.plugins.base import Plugin
class Local(Plugin):
    name = "NAME"
    version = "1"
    def register_routes(self, app, prefix): pass
'''
    for directory, name in (("json", "good"), ("duplicate", "good"), ("outside", "../escape")):
        package = tmp_path / directory
        package.mkdir()
        (package / "__init__.py").write_text(source.replace("NAME", name))
    discovered = discover_plugins([str(tmp_path)])
    assert [plugin.name for plugin in discovered] == ["good"]
    import json
    assert json.loads('{"intact": true}') == {"intact": True}
