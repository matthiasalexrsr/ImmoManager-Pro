"""Migration c9e4a7d2f1b6 (dunning) on SQLite: additive upgrade over existing data, constraints,
refused downgrade while dunning data exists, clean round trip, adoption of a create_all database."""

import sqlite3

import pytest
from test_migrations import _schema, _seed_previous_schema, _version, migrate  # noqa: F401  (fixture)

from backend.db.dunning_models import DUNNING_TABLES
from backend.db.orm_models import Base

DUNNING_REVISION = "c9e4a7d2f1b6"
PREVIOUS = "c9f4a2e7b1d5"


def test_dunning_upgrade_constraints_and_guarded_downgrade(migrate):  # noqa: F811
    db_path = migrate(PREVIOUS)
    _seed_previous_schema(db_path)
    migrate(DUNNING_REVISION)
    assert set(DUNNING_TABLES) <= set(_schema(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        contract = conn.execute("SELECT id FROM contracts").fetchone()[0]
        conn.execute("INSERT INTO dunning_cases (id, contract_id, reference, opened_on) "
                     "VALUES ('c1', ?, 'M-2026-AAAAAAAA', '2026-07-10')", (contract,))
        assert conn.execute("SELECT status, stage FROM dunning_cases").fetchone() == ("open", 0)
        with pytest.raises(sqlite3.IntegrityError):        # one open case per contract
            conn.execute("INSERT INTO dunning_cases (id, contract_id, reference, opened_on) "
                         "VALUES ('c2', ?, 'M-2026-BBBBBBBB', '2026-07-11')", (contract,))
        with pytest.raises(sqlite3.IntegrityError):        # a closed case needs its result
            conn.execute("UPDATE dunning_cases SET status = 'closed' WHERE id = 'c1'")
        conn.execute("UPDATE dunning_cases SET status = 'closed', result = 'paid' WHERE id = 'c1'")
        conn.execute("INSERT INTO dunning_cases (id, contract_id, reference, opened_on) "
                     "VALUES ('c2', ?, 'M-2026-BBBBBBBB', '2026-07-11')", (contract,))
        with pytest.raises(sqlite3.IntegrityError):        # a final letter names its document
            conn.execute("INSERT INTO dunning_letters (id, case_id, contract_id, stage, status, letter_date, "
                         "payment_deadline, principal, total, content, draft_hash) VALUES ('l1', 'c2', ?, 1, "
                         "'final', '2026-07-11', '2026-07-25', 1, 1, '{}', 'h')", (contract,))
        with pytest.raises(sqlite3.IntegrityError):        # an assigned reply names its case
            conn.execute("INSERT INTO dunning_replies (id, received_on, body, status) "
                         "VALUES ('r1', '2026-07-12', 'x', 'assigned')")
    with pytest.raises(RuntimeError, match="dunning_cases"):
        migrate.downgrade(PREVIOUS)
    assert _version(db_path) == DUNNING_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM dunning_cases")
    migrate.downgrade(PREVIOUS)
    schema = _schema(db_path)
    assert not set(DUNNING_TABLES) & set(schema) and _version(db_path) == PREVIOUS
    with sqlite3.connect(db_path) as conn:        # existing data survives the round trip
        assert conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] >= 1
    migrate()
    assert set(DUNNING_TABLES) <= set(_schema(db_path)) and _version(db_path) == migrate.head


def test_dunning_tables_of_a_create_all_database_are_adopted(migrate):  # noqa: F811
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    migrate()
    assert set(DUNNING_TABLES) <= set(_schema(migrate.db_path))
    migrate.downgrade(PREVIOUS)
    assert not set(DUNNING_TABLES) & set(_schema(migrate.db_path))
    migrate()
    assert _version(migrate.db_path) == migrate.head
