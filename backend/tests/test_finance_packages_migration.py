"""Finance's assigned additive migration, including create_all adoption."""
import sqlite3

from test_migrations import _seed_previous_schema, _version, migrate  # noqa: F401


def test_finance_upgrade_preserves_every_prior_column_and_opaque_partial(migrate):  # noqa: F811
    path = migrate("d73f2b9a041c")
    _seed_previous_schema(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE receivables SET status='partial'")
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'alembic_version'")]
        columns = {name: [r[1] for r in connection.execute(f'PRAGMA table_info("{name}")')] for name in tables}
        before = {name: connection.execute('SELECT ' + ','.join(f'"{c}"' for c in columns[name]) + f' FROM "{name}" ORDER BY rowid').fetchall() for name in tables}
    migrate("e160a1b2c302")
    with sqlite3.connect(path) as connection:
        for name in tables:
            after = connection.execute('SELECT ' + ','.join(f'"{c}"' for c in columns[name]) + f' FROM "{name}" ORDER BY rowid').fetchall()
            assert after == before[name], name
        assert connection.execute("SELECT count(*) FROM receivable_settlements").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM saved_finance_reports").fetchone()[0] == 0
    assert _version(path) == "e160a1b2c302"


def test_finance_create_all_adoption(migrate):  # noqa: F811
    from sqlalchemy import create_engine

    from backend.db.orm_models import Base
    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    migrate("e160a1b2c302")
    assert _version(migrate.db_path) == "e160a1b2c302"
