"""Prepared pure fixture guards: no app, model, engine or DBAPI creation."""

import pytest

from backend.tests import notification_inbox_pg_proposal_support as support


@pytest.mark.parametrize("source,port", [
    ("postgresql://immo_ci@127.0.0.1:58112/immo_ci", 58112),
    ("postgresql://immo_ci:synthetic%23value@localhost:5432/immo_ci", 5432),
])
def test_dedicated_url_keeps_only_explicit_loopback_target(source, port):
    url = support.dedicated_url(source)
    assert url.drivername == "postgresql+psycopg2"
    assert (url.username, url.host, url.port, url.database) == ("immo_ci", "127.0.0.1", port, "immo_ci")
    assert not url.query


@pytest.mark.parametrize("source", [
    None,
    "not-a-url synthetic-sensitive-value",
    "postgresql://immo_ci@remote.example.invalid:58112/immo_ci",
    "postgresql://immo_ci@127.0.0.1/immo_ci",
    "postgresql://immo_ci@127.0.0.1:5433/immo_ci",
    "postgresql://other@127.0.0.1:58112/immo_ci",
    "postgresql://immo_ci@127.0.0.1:58112/other",
    "postgresql://immo_ci@/immo_ci",
    "postgresql+untrusted://immo_ci@127.0.0.1:58112/immo_ci",
    "postgresql://immo_ci@127.0.0.1:58112/immo_ci?host=remote.example.invalid",
    "postgresql://immo_ci@127.0.0.1:58112/immo_ci?hostaddr=198.51.100.1",
    "postgresql://immo_ci@127.0.0.1:58112/immo_ci?service=other",
    "postgresql://immo_ci@127.0.0.1:58112/immo_ci?options=-csearch_path=public",
    "postgresql://immo_ci@127.0.0.1:58112/immo_ci?options=-crole=other",
])
def test_bad_pg_url_refuses_before_engine_creation_without_value_output(source, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected PG target may not reach engine construction")

    monkeypatch.setattr(support, "create_engine", forbidden)
    with pytest.raises(ValueError) as refused:
        with support.postgres_proposal_database(source):
            pytest.fail("Rejected PG target may not yield")
    assert str(refused.value) == "notification_inbox_pg_target_invalid"


def test_schema_and_deadline_refuse_before_engine_creation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid PG fixture boundaries may not construct an engine")

    monkeypatch.setattr(support, "create_engine", forbidden)
    source = "postgresql://immo_ci@127.0.0.1:58112/immo_ci"
    with pytest.raises(ValueError, match="^notification_inbox_pg_schema_invalid$"):
        support._engine(source, "public", float("inf"))
    with pytest.raises(TimeoutError, match="^notification_inbox_pg_node_timeout$"):
        support._engine(source, "pg_catalog", 0)
