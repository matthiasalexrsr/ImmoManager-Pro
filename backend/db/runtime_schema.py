"""Read-only structural compatibility check for explicitly migrated servers."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from .orm_models import Base


class RuntimeSchemaError(RuntimeError):
    """Fixed operator guidance, safe to preserve across initialization layers."""


def validate_runtime_schema(engine) -> None:
    """Never create, stamp, seed, or repair an installation during startup.

    Call after the application's metadata registration. Extra physical columns
    are harmless; missing declared tables/columns or a different migration head
    require explicit maintenance. This is not a data-integrity/backup check.
    """
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations").replace("%", "%%"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    if len(expected) != 1:
        raise RuntimeSchemaError("Server migration history is not linear; use a verified release before starting.")
    with engine.connect() as connection:
        actual = set(MigrationContext.configure(connection).get_current_heads())
        if actual != expected:
            raise RuntimeSchemaError(
                "Server database migration revision is missing or incompatible. Stop the app, preserve a full backup, "
                "and run the explicit installation/upgrade procedure for this release; startup will not migrate or stamp it."
            )
        inspector = inspect(connection)
        present = set(inspector.get_table_names())
        for name, table in Base.metadata.tables.items():
            if name not in present or not set(table.c.keys()) <= {
                column["name"] for column in inspector.get_columns(name)
            }:
                raise RuntimeSchemaError(
                    "Server database schema is incomplete. Restore a complete compatible backup or perform an "
                    "explicit schema repair; startup will not create missing tables or columns."
                )
        from ..services.measurement_history_validation import MeasurementIntegrityError
        from .measurement_history_schema import validate_measurement_guards, validate_measurement_schema
        try:
            if not validate_measurement_schema(connection):
                raise MeasurementIntegrityError("missing measurement family")
            validate_measurement_guards(connection)
        except MeasurementIntegrityError:
            raise RuntimeSchemaError(
                "Server historical source schema or original protection is incomplete. Explicit migration or "
                "compatible full restore is required; startup will not repair it."
            ) from None
