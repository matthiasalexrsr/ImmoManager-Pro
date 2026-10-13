"""PostgreSQL client credentials stay out of process command lines."""

from sqlalchemy.engine import make_url

from backend.services.full_backup import _libpq


def test_libpq_password_is_only_passed_in_child_environment(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "unrelated-inherited-password")
    conninfo, environment = _libpq("postgresql+psycopg2://alice:only%40in%3Aenvironment@localhost:5432/demo?sslmode=require")
    parsed = make_url(conninfo)
    assert parsed.password is None
    assert environment["PGPASSWORD"] == "only@in:environment"
    assert parsed.drivername == "postgresql"
    assert parsed.username == "alice"
    assert parsed.host == "localhost"
    assert parsed.port == 5432
    assert parsed.database == "demo"
    assert parsed.query == {"sslmode": "require"}
