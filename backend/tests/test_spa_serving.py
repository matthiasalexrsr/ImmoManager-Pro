"""Built-frontend serving must never expose files outside frontend/dist."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import _mount_spa


@pytest.fixture
def client(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (dist / "robots.txt").write_text("robots", encoding="utf-8")
    (tmp_path / "secret.env").write_text("JWT_SECRET_KEY=leak", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/v1/known")
    def known():
        return {"ok": True}

    _mount_spa(app, dist)
    return TestClient(app)


@pytest.mark.parametrize("path", [
    "/..%2Fsecret.env",
    "/%2e%2e/secret.env",
    "/assets/..%2F..%2Fsecret.env",
])
def test_parent_traversal_is_not_served(client, path):
    resp = client.get(path)
    assert "leak" not in resp.text


def test_absolute_path_is_not_served(client, tmp_path):
    resp = client.get("/" + str(tmp_path / "secret.env").replace("/", "%2F"))
    assert "leak" not in resp.text
    assert resp.text == "<html>spa</html>"


def test_files_inside_dist_are_served(client):
    assert client.get("/robots.txt").text == "robots"


def test_client_routes_fall_back_to_index(client):
    resp = client.get("/properties/123")
    assert resp.status_code == 200
    assert resp.text == "<html>spa</html>"


def test_unknown_api_route_is_404_not_spa(client):
    assert client.get("/api/v1/known").json() == {"ok": True}
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert "spa" not in resp.text
