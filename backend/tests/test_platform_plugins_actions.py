"""Real persisted plugin upgrades and the normal scoped action facade."""

from copy import deepcopy
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from backend import auth
from backend.db.access_models import PluginInstallationORM
from backend.dependencies import store
from backend.models import ContactCreate
from backend.plugins.base import Plugin
from backend.plugins.lifecycle import change, validate_schema
from backend.plugins.runtime import start_plugins, stop_plugins
from backend.routers import safe_actions
from backend.services.workspace_contexts import resolve_context


def schema(fields):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(fields),
        "properties": {name: {"type": kind} for name, kind in fields.items()},
    }


@pytest.mark.parametrize("properties,required", [
    ([], ["original"]),
    ({"original": {"type": "string"}}, ["original", "original"]),
    ({"original": object()}, ["original"]),
    ({"original": {"type": "string"}}, ["unknown"]),
])
def test_invalid_plugin_field_declarations_are_rejected_before_data_migration(properties, required):
    with pytest.raises(ValueError):
        validate_schema({"type": "object", "additionalProperties": False,
                         "properties": properties, "required": required}, None, declaration=True)


class Synthetic(Plugin):
    name = "synthetic"
    version = "1.0.0"
    data_manifest = {
        "api_version": 1,
        "schema_version": 1,
        "capabilities": ["owned_data", "owner_routes"],
        "migrations": [1],
        "schemas": {"1": schema({"retained": "string"})},
    }
    data_migrations = {1: lambda prior: {"retained": "Original\x00ä"}}

    def register_routes(self, app, prefix):
        @app.get("/info")
        def info():
            return {"version": self.version}


def version_two():
    plugin = Synthetic()
    plugin.version = "2.0.0"
    plugin.data_manifest = deepcopy(plugin.data_manifest)
    plugin.data_manifest.update(schema_version=2, migrations=[1, 2])
    plugin.data_manifest["schemas"]["2"] = schema({"retained": "string", "count": "integer"})
    plugin.data_migrations = {**plugin.data_migrations, 2: lambda prior: {**prior, "count": 17}}
    return plugin


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    return auth.register_user("platform-owner", "owner@example.test", "Owner", "Secret123", "eigentuemer")


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'plugins.db'}")
    cast(Table, PluginInstallationORM.__table__).create(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def call(factory, plugin, owner, operation="upgrade", revision=0, **kwargs):
    return change(
        factory,
        plugin,
        actor_id=owner.id,
        operation=operation,
        expected_revision=revision,
        idempotency_key=kwargs.pop("key", str(uuid4())),
        **kwargs,
    )


def test_real_upgrade_restart_replay_uninstall_and_full_owned_restore(factory, owner):
    first, second = Synthetic(), version_two()
    call(factory, first, owner)
    key = str(uuid4())
    result = call(factory, second, owner, revision=1, key=key)
    assert result == call(factory, second, owner, revision=1, key=key)
    assert result["schema_version"] == 2 and result["backup_revisions"] == [1]
    with factory() as session:
        assert session.get(PluginInstallationORM, "synthetic").payload == {"retained": "Original\x00ä", "count": 17}
    app = FastAPI()
    start_plugins(app, [second], factory)
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    assert client.get("/api/v1/plugins/synthetic/info").json() == {"version": "2.0.0"}
    assert TestClient(app).get("/api/v1/plugins/synthetic/info").status_code == 401
    # A plugin mount must explicitly refuse unsupported ASGI transports,
    # not hang forever or accept unguarded WebSocket handshakes.
    with pytest.raises(WebSocketDisconnect) as denied_socket:
        with client.websocket_connect("/api/v1/plugins/synthetic/socket"):
            pass
    assert denied_socket.value.code == 1008
    call(factory, second, owner, operation="uninstall", revision=2)
    stop_plugins(app, [second])
    assert client.get("/api/v1/plugins/synthetic/info").status_code == 404
    restored = call(factory, second, owner, operation="restore", revision=3, backup_revision=1)
    assert restored["enabled"] is False and restored["version"] == "1.0.0"
    with factory() as session:
        assert session.get(PluginInstallationORM, "synthetic").payload == {"retained": "Original\x00ä"}
    start_plugins(app, [second], factory)
    assert second.runtime_status == "not_installed"
    # Reinstall compatible executable and migrate the restored data through the same production path.
    call(factory, second, owner, revision=4)
    start_plugins(app, [second], factory)
    assert second.runtime_status == "active"
    stop_plugins(app, [second])


def test_failed_migration_rolls_back_everything_and_can_retry(factory, owner):
    call(factory, Synthetic(), owner)
    plugin = version_two()
    plugin.data_migrations[2] = lambda prior: {"retained": "damaged", "count": "wrong"}
    with pytest.raises(ValueError):
        call(factory, plugin, owner, revision=1)
    with factory() as session:
        row = session.get(PluginInstallationORM, "synthetic")
        assert row.revision == 1 and row.payload == {"retained": "Original\x00ä"} and row.backups == []
    assert call(factory, version_two(), owner, revision=1)["revision"] == 2


def test_plugin_conflicts_and_revoked_owner_on_replay(factory, owner):
    key = str(uuid4())
    call(factory, Synthetic(), owner, key=key)
    with pytest.raises(HTTPException) as stale:
        call(factory, version_two(), owner)
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as conflict:
        call(factory, version_two(), owner, key=key)
    assert conflict.value.status_code == 409
    auth.update_user(owner.id, {"role": "readonly"})
    with pytest.raises(HTTPException) as denied:
        call(factory, Synthetic(), owner, key=key)
    assert denied.value.status_code == 403


def test_facade_uses_normal_source_revision_idempotency_and_no_gateway():
    name = "facade-" + uuid4().hex
    owner = auth.register_user(name, name + "@example.test", "Facade", "Secret123", "eigentuemer")
    contact = store.create_contact(ContactCreate(first_name="Facade", last_name="Fixture"))
    app = FastAPI()
    app.include_router(safe_actions.router)
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    source = resolve_context(store, "contact", contact.id, owner.id)
    body = {
        "action": "favorite.set",
        "source_kind": "contact",
        "source_id": contact.id,
        "source_revision": source["revision"],
        "base_revision": 0,
        "idempotency_key": str(uuid4()),
        "confirmed": True,
    }
    first = client.post("/workspace/actions", json=body)
    assert first.status_code == 200, first.text
    assert client.post("/workspace/actions", json=body).json() == first.json()
    assert client.post("/workspace/actions", json={**body, "source_revision": "stale"}).status_code == 409
    assert client.post("/workspace/actions", json={**body, "action": "bookings.create"}).status_code == 422
    assert client.post("/workspace/actions", json={**body, "confirmed": False}).status_code == 422
    assert client.post("/workspace/actions", json={**body, "path": "/admin/restore"}).status_code == 422
    auth.update_user(owner.id, {"is_active": False})
    assert client.post("/workspace/actions", json=body).status_code in (401, 403)


def test_actual_declared_package_upgrade_executes_new_version(factory, owner, tmp_path):
    import hashlib
    import json

    from backend.plugins import discover_plugins

    package = tmp_path / "packages" / "synthetic_package"
    package.mkdir(parents=True)

    def write(version):
        plugin = Synthetic() if version == 1 else version_two()
        source = (
            "from backend.plugins.base import Plugin\nclass Declared(Plugin):\n"
            f" name='synthetic'\n version='{version}.0.0'\n data_manifest={plugin.data_manifest!r}\n"
            " data_migrations={1:lambda prior:{'retained':'Original\\x00ä'},2:lambda prior:{**prior,'count':17}}\n"
            " def register_routes(self, app, prefix): pass\n"
        )
        (package / "__init__.py").write_bytes(source.encode("utf-8"))
        (package / "immomanager-plugin.json").write_text(
            json.dumps(
                {
                    "name": "synthetic",
                    "version": f"{version}.0.0",
                    "files": {"__init__.py": hashlib.sha256(source.encode()).hexdigest()},
                }
            ),
            encoding="utf-8",
        )

    write(1)
    (first,) = discover_plugins([str(package.parent)])
    assert call(factory, first, owner)["version"] == "1.0.0"
    write(2)
    (second,) = discover_plugins([str(package.parent)])
    assert call(factory, second, owner, revision=1)["version"] == "2.0.0"
    with factory() as session:
        row = session.get(PluginInstallationORM, "synthetic")
        assert row.payload == {"retained": "Original\x00ä", "count": 17}
        assert row.manifest["package"]["files"] != row.backups[0]["manifest"]["package"]["files"]
