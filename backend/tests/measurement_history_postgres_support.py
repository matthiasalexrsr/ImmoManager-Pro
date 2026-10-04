"""One owned random schema per native gate; never touch public or the service."""

import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@contextmanager
def migrated_postgres(monkeypatch):
    source = os.getenv("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.skip("TEST_SERVER_DATABASE_URL needs a dedicated disposable PostgreSQL")
    url = make_url(source)
    assert url.get_backend_name() == "postgresql"
    schema = "measurement_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    scoped = url.update_query_dict({"options": "-csearch_path=" + schema})
    engine = create_engine(scoped, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        monkeypatch.setenv("DATABASE_URL", scoped.render_as_string(hide_password=False))
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        yield engine, config
    finally:
        engine.dispose()
        assert schema.startswith("measurement_") and len(schema) == 44
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
