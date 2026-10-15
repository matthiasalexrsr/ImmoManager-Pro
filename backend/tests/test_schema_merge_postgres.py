"""Actual PostgreSQL upgrades from both pre-merge October schema branches."""

import pytest
from alembic import command
from test_document_versions_postgres import postgres  # noqa: F401
from test_schema_merge import DATE_INDEX, TAKEOVER, _exercise_existing_branch


@pytest.mark.parametrize("revision", [DATE_INDEX, TAKEOVER])
def test_postgres_upgrades_either_existing_branch(postgres, revision):  # noqa: F811
    engine, config = postgres
    command.downgrade(config, "3c7e9a1d5f20")
    _exercise_existing_branch(engine, config, revision)
