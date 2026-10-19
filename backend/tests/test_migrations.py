"""Alembic migrations build the schema the ORM uses, also on existing databases."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

import backend.models  # noqa: F401  (adds the UI contract columns to the ORM)
from backend.db.orm_models import Base

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_HEAD = "f6a1b2c3d4e5"


@pytest.fixture
def migrate(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)  # env.py prefers it over the config
    config = Config()  # no ini file: keeps alembic from reconfiguring logging
    config.set_main_option("script_location", str(ROOT / "backend" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    def run(revision: str = "head") -> Path:
        command.upgrade(config, revision)
        return db_path

    run.downgrade = lambda revision: command.downgrade(config, revision)  # type: ignore[attr-defined]
    run.head = ScriptDirectory.from_config(config).get_current_head()  # type: ignore[attr-defined]
    run.db_path = db_path  # type: ignore[attr-defined]
    return run


def _schema(db_path: Path) -> dict[str, set[str]]:
    with sqlite3.connect(db_path) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")} for table in tables}


def _missing_from(schema: dict[str, set[str]]) -> dict[str, list[str]]:
    missing = {}
    for table in Base.metadata.sorted_tables:
        absent = sorted({column.name for column in table.columns} - schema.get(table.name, set()))
        if absent:
            missing[table.name] = absent
    return missing


def _version(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _seed_previous_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO portfolios (id, name, currency, timezone, status, created_at, updated_at)
                VALUES ('pf', 'Bestand', 'EUR', 'Europe/Berlin', 'active', '2025-01-01', '2025-01-01');
            INSERT INTO properties (id, portfolio_id, name, property_type, status, created_at, updated_at)
                VALUES ('pr', 'pf', 'MFH', 'residential', 'active', '2025-01-01', '2025-01-01');
            INSERT INTO units (id, property_id, label, unit_type, status, area_sqm, created_at, updated_at)
                VALUES ('u1', 'pr', 'WE 1', 'residential', 'occupied', 60, '2025-01-01', '2025-01-01');
            INSERT INTO tenants (id, full_name, created_at, updated_at)
                VALUES ('t1', 'Mia Muster', '2025-01-01', '2025-01-01');
            INSERT INTO billing_periods (id, property_id, label, start_date, end_date, status, created_at, updated_at)
                VALUES ('bp', 'pr', 'BK 2024', '2024-01-01', '2024-12-31', 'draft', '2025-01-01', '2025-01-01');
            INSERT INTO allocation_keys (id, property_id, name, key_type, created_at, updated_at)
                VALUES ('k', 'pr', 'Fläche', 'area_sqm', '2025-01-01', '2025-01-01');
            INSERT INTO cost_items (id, billing_period_id, description, amount, allocation_key_id, created_at, updated_at)
                VALUES ('ci', 'bp', 'Grundsteuer', 400, 'k', '2025-01-01', '2025-01-01');
            INSERT INTO contracts (id, contract_number, property_id, unit_id, tenant_id, status, start_date,
                                   created_at, updated_at)
                VALUES ('c1', 'V-1', 'pr', 'u1', 't1', 'active', '2020-01-01', '2025-01-01', '2025-01-01');
            INSERT INTO utility_statements (id, billing_period_id, contract_id, unit_id, total_cost, advance_paid,
                                            balance, status, created_at, updated_at)
                VALUES ('s1', 'bp', 'c1', 'u1', 400, 1800, -1400, 'draft', '2025-01-01', '2025-01-01');
        """)


def test_migrations_build_the_orm_schema(migrate):
    """Regression: a database built by the migrations lacked 2 tables and 29 columns of the ORM."""
    db_path = migrate()

    assert _missing_from(_schema(db_path)) == {}


def test_upgrade_keeps_existing_rows(migrate):
    db_path = migrate(PREVIOUS_HEAD)
    _seed_previous_schema(db_path)

    migrate()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT description, is_recoverable FROM cost_items").fetchall() == [("Grundsteuer", 1)]
        assert conn.execute("SELECT archived FROM tenants").fetchall() == [(0,)]
        # Existing statements survive the table rebuild and count as tenant rows.
        assert conn.execute("SELECT contract_id, party, balance FROM utility_statements").fetchall() == [
            ("c1", "tenant", -1400)]
        # Vacancy rows have no contract.
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("""INSERT INTO utility_statements (id, billing_period_id, contract_id, unit_id, party, total_cost,
                        advance_paid, balance, status, created_at, updated_at)
                        VALUES ('s2', 'bp', NULL, 'u1', 'vacancy', 10, 0, 10, 'draft', '2025-01-01', '2025-01-01')""")
    assert _version(db_path) == migrate.head


def test_upgrade_gives_every_contract_its_rent_history(migrate):
    """Rents lived only on the unit; contracts get periods from start and applied adjustments."""
    db_path = migrate(PREVIOUS_HEAD)
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            UPDATE units SET cold_rent = 820, service_charge_advance = 190, heating_advance = 100;
            INSERT INTO rent_adjustments (id, contract_id, adjustment_type, effective_date, previous_rent, new_rent,
                                          status, created_at, updated_at)
                VALUES ('ra', 'c1', 'index', '2025-01-01', 780, 820, 'applied', '2025-01-01', '2025-01-01');
        """)

    migrate()
    migrate()  # running again adds nothing

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT valid_from, cold_rent, service_charge_advance, heating_advance, source, "
                            "rent_adjustment_id FROM contract_rent_periods ORDER BY valid_from").fetchall()
    assert rows == [("2020-01-01", 780, 190, 100, "contract_start", None),
                    ("2025-01-01", 820, 190, 100, "adjustment", "ra")]


def test_database_created_without_migrations_is_adopted(migrate):
    """create_all() databases (desktop installs) have no alembic_version; upgrading them used to fail."""
    db_path = migrate(PREVIOUS_HEAD)
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE alembic_version")

    migrate()

    assert _version(db_path) == migrate.head
    assert _missing_from(_schema(db_path)) == {}


def test_database_created_by_create_all_upgrades_cleanly(migrate):
    """A current desktop database already has every column; adopting it must not fail."""
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    migrate()

    assert _version(migrate.db_path) == migrate.head
    assert _missing_from(_schema(migrate.db_path)) == {}


def test_document_tenant_upgrade_keeps_legacy_null_links(migrate):
    db_path = migrate("a1d6c3f8e2b4")
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO documents (id, contract_id, title, file_url, created_at, updated_at)
                VALUES ('legacy', 'c1', 'Alter Mietvertrag', '/legacy.pdf', '2025-01-01', '2025-01-01');
            INSERT INTO documents (id, title, file_url, created_at, updated_at)
                VALUES ('general', 'Allgemein', '/general.pdf', '2025-01-01', '2025-01-01');
            INSERT INTO invoices (id, supplier, invoice_date, net_amount, vat_amount, gross_amount, status,
                                  source_document_id, created_at, updated_at)
                VALUES ('invoice', 'Firma', '2025-01-01', 100, 19, 119, 'open', 'general', '2025-01-01', '2025-01-01');
        """)
    migrate()
    migrate()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, tenant_id, contract_id FROM documents ORDER BY id").fetchall() == [
            ("general", None, None), ("legacy", None, "c1"),
        ]
        assert any(row[2] == "tenants" and row[3] == "tenant_id" and row[6] == "SET NULL"
                   for row in conn.execute("PRAGMA foreign_key_list(documents)"))
        assert "idx_documents_tenant" in {row[1] for row in conn.execute("PRAGMA index_list(documents)")}
        assert conn.execute("SELECT source_document_id FROM invoices WHERE id='invoice'").fetchone() == ("general",)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("UPDATE documents SET tenant_id='t1' WHERE id='general'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE documents SET tenant_id='missing' WHERE id='general'")
    assert _version(db_path) == migrate.head


def test_document_tenant_downgrade_refuses_to_lose_associations(migrate):
    db_path = migrate()
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""INSERT INTO documents (id, tenant_id, title, file_url, created_at, updated_at)
                        VALUES ('direct', 't1', 'Antrag', '/direct.pdf', '2025-01-01', '2025-01-01')""")
    with pytest.raises(RuntimeError, match="tenant-linked documents exist"):
        migrate.downgrade("a1d6c3f8e2b4")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT tenant_id FROM documents WHERE id='direct'").fetchone() == ("t1",)
        assert "idx_documents_tenant" in {row[1] for row in conn.execute("PRAGMA index_list(documents)")}
    # Later additive migrations can already have been downgraded. The document
    # revision itself must remain applied when its destructive downgrade refuses.
    assert _version(db_path) == "6e2f8a4c9b71"


def test_document_tenant_downgrade_keeps_unassigned_documents(migrate):
    db_path = migrate()
    with sqlite3.connect(db_path) as conn:
        conn.execute("""INSERT INTO documents (id, title, file_url, created_at, updated_at)
                        VALUES ('legacy', 'Alt', '/legacy.pdf', '2025-01-01', '2025-01-01')""")
    migrate.downgrade("a1d6c3f8e2b4")
    assert "tenant_id" not in _schema(db_path)["documents"]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, title FROM documents").fetchall() == [("legacy", "Alt")]
    assert _version(db_path) == "a1d6c3f8e2b4"


def test_document_tenant_downgrade_on_adopted_schema_keeps_invoice_links(migrate):
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import Engine

    def foreign_keys_on(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    event.listen(Engine, "connect", foreign_keys_on)
    try:
        engine = create_engine(f"sqlite:///{migrate.db_path}")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("""INSERT INTO documents (id, title, file_url, created_at, updated_at)
                                          VALUES ('doc', 'Quelle', '/source.pdf', '2025-01-01', '2025-01-01')""")
            connection.exec_driver_sql("""INSERT INTO invoices
                (id, supplier, invoice_date, net_amount, vat_amount, vat_rate, gross_amount, status,
                 source_document_id, created_at, updated_at)
                VALUES ('invoice', 'Firma', '2025-01-01', 100, 19, 19, 119, 'open', 'doc', '2025-01-01', '2025-01-01')""")
        engine.dispose()
        migrate()
        migrate.downgrade("a1d6c3f8e2b4")
        with sqlite3.connect(migrate.db_path) as conn:
            assert conn.execute("SELECT source_document_id FROM invoices").fetchall() == [("doc",)]
            assert conn.execute("SELECT id FROM documents").fetchall() == [("doc",)]
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert "tenant_id" not in _schema(migrate.db_path)["documents"]
    finally:
        event.remove(Engine, "connect", foreign_keys_on)


ARCHIVE_PARENT = "d7a2f9c4e681"


def _seed_original(db_path: Path) -> None:
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO documents (id, property_id, unit_id, contract_id, title, file_url, created_at, updated_at)
                VALUES ('d1', 'pr', 'u1', 'c1', 'WGB', '/uploads/housing-confirmations/d1.pdf',
                        '2025-01-01', '2025-01-01');
            INSERT INTO document_versions (id, document_id, portfolio_id, property_id, unit_id, contract_id,
                tenant_id, number, actor_id, idempotency_key, request_sha256, operation, comment, filename,
                media_type, sha256, size_bytes, metadata_snapshot, created_at)
                VALUES ('v1', 'd1', 'pf', 'pr', 'u1', 'c1', 't1', 1, 'owner', 'k',
                        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'archive_original', '',
                        'd1.pdf', 'application/pdf',
                        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 3, '{}', '2025-01-01');
            INSERT INTO document_version_chunks (version_id, position, portfolio_id, data)
                VALUES ('v1', 0, 'pf', X'255044');
        """)


def test_document_originals_are_guarded_after_the_upgrade(migrate):
    db_path = migrate()
    _seed_original(db_path)
    with sqlite3.connect(db_path) as conn:
        triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {"immo_document_versions_update", "immo_document_versions_delete",
                "immo_document_version_chunks_update", "immo_document_version_chunks_delete"} <= triggers
        for statement in ("UPDATE document_versions SET comment = 'x'", "DELETE FROM document_version_chunks"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(statement)


def test_document_originals_downgrade_refuses_to_destroy_evidence(migrate):
    db_path = migrate()
    _seed_original(db_path)
    with pytest.raises(RuntimeError, match="Document originals exist"):
        migrate.downgrade(ARCHIVE_PARENT)
    assert {"document_versions", "document_version_chunks"} <= set(_schema(db_path))
    assert _version(db_path) == "e5f1a7c3b9d2"     # the archive revision stays applied


def test_document_originals_downgrade_without_originals(migrate):
    db_path = migrate()
    migrate.downgrade(ARCHIVE_PARENT)
    assert not {"document_versions", "document_version_chunks"} & set(_schema(db_path))
    migrate()
    assert {"document_versions", "document_version_chunks"} <= set(_schema(db_path))


ACCESS_PARENT = "e5f1a7c3b9d2"
ACCESS_REVISION = "a7c2e9f4b1d3"


def _seed_users(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO users (id, username, email, full_name, hashed_password, role, is_active, totp_enabled,
                               created_at, updated_at)
                VALUES ('owner', 'owner', 'o@example.com', 'Owner', 'x', 'eigentuemer', 1, 0,
                        '2025-01-01', '2025-01-01'),
                       ('staff', 'staff', 's@example.com', 'Staff', 'x', 'verwalter', 1, 0,
                        '2025-01-01', '2025-01-01');
        """)


def test_portfolio_access_upgrade_keeps_what_every_account_could_see(migrate):
    db_path = migrate(ACCESS_PARENT)
    _seed_previous_schema(db_path)
    _seed_users(db_path)
    migrate()
    with sqlite3.connect(db_path) as conn:
        rows = dict(conn.execute("SELECT user_id, mode || '/' || origin FROM user_portfolio_access"))
    assert rows == {"owner": "all/legacy_all", "staff": "all/legacy_all"}


def test_portfolio_access_downgrade_refuses_to_widen_access(migrate):
    db_path = migrate(ACCESS_PARENT)
    _seed_previous_schema(db_path)
    _seed_users(db_path)
    migrate()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE user_portfolio_access SET mode = 'selected' WHERE user_id = 'staff'")
    with pytest.raises(RuntimeError, match="Restricted accounts exist"):
        migrate.downgrade(ACCESS_PARENT)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE user_portfolio_access SET mode = 'all' WHERE user_id = 'staff'")
        conn.execute("INSERT INTO user_portfolio_grants (user_id, portfolio_id) VALUES ('staff', 'pf')")
    with pytest.raises(RuntimeError, match="Portfolio grants exist"):
        migrate.downgrade(ACCESS_PARENT)
    assert _version(db_path) == ACCESS_REVISION     # later revisions went down, this one refused
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM user_portfolio_grants")
    migrate.downgrade(ACCESS_PARENT)
    assert "user_portfolio_access" not in _schema(db_path)


JOBS_REVISION = "b8e3d5f7a2c4"


def test_durable_jobs_upgrade_and_downgrade(migrate):
    db_path = migrate(ACCESS_REVISION)
    _seed_previous_schema(db_path)
    migrate(JOBS_REVISION)
    schema = _schema(db_path)
    assert {"job_runs", "job_occurrences"} <= set(schema)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO job_runs (id, kind, idempotency_key, scope, status, payload, attempts, "
                     "max_attempts, available_at) VALUES ('r1', 'tasks.recurring', 'k1', 'installation', "
                     "'running', '{}', 1, 5, '2026-10-07')")
        conn.execute("INSERT INTO job_occurrences (rule_key, rule_version, occurrence_key, status) "
                     "VALUES ('task:t', 'v1', '2026-10-07', 'created')")
        with pytest.raises(sqlite3.IntegrityError):    # the dedupe is the primary key
            conn.execute("INSERT INTO job_occurrences (rule_key, rule_version, occurrence_key, status) "
                         "VALUES ('task:t', 'v1', '2026-10-07', 'skipped')")
        with pytest.raises(sqlite3.IntegrityError):    # installation scope only
            conn.execute("INSERT INTO job_runs (id, kind, idempotency_key, scope, status, payload, attempts, "
                         "max_attempts, available_at) VALUES ('r2', 'x', 'k2', 'portfolio', 'queued', '{}', "
                         "0, 5, '2026-10-07')")
    with pytest.raises(RuntimeError, match="Unfinished jobs exist"):
        migrate.downgrade(ACCESS_REVISION)
    assert _version(db_path) == JOBS_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE job_runs SET status = 'succeeded'")
    migrate.downgrade(ACCESS_REVISION)
    assert "job_runs" not in _schema(db_path) and "job_occurrences" not in _schema(db_path)
    assert _version(db_path) == ACCESS_REVISION
    migrate()
    assert {"job_runs", "job_occurrences"} <= set(_schema(db_path))


BILLING_REGRESSION_REVISION = "c3e8a1f5d9b7"


def test_billing_regression_upgrade_and_downgrade(migrate):
    db_path = migrate(JOBS_REVISION)
    _seed_previous_schema(db_path)
    migrate(BILLING_REGRESSION_REVISION)
    schema = _schema(db_path)
    assert {"contract_occupancies", "billing_objections"} <= set(schema)
    assert {"measure_unit", "removal_date"} <= schema["meters"]
    assert {"revision", "corrects_period_id", "revision_notes"} <= schema["billing_periods"]
    assert {"advance_sections", "final_document"} <= schema["utility_statements"]
    with sqlite3.connect(db_path) as conn:
        # existing periods are revision 1 and correct nothing
        assert conn.execute("SELECT revision, corrects_period_id FROM billing_periods").fetchall() == [(1, None)]
        conn.execute("INSERT INTO contract_occupancies (id, contract_id, valid_from, persons) "
                     "VALUES ('o1', 'c1', '2025-07-01', 3)")
        with pytest.raises(sqlite3.IntegrityError):    # one entry per contract and date
            conn.execute("INSERT INTO contract_occupancies (id, contract_id, valid_from, persons) "
                         "VALUES ('o2', 'c1', '2025-07-01', 2)")
        with pytest.raises(sqlite3.IntegrityError):    # no negative household
            conn.execute("INSERT INTO contract_occupancies (id, contract_id, valid_from, persons) "
                         "VALUES ('o3', 'c1', '2025-08-01', -1)")
    with pytest.raises(RuntimeError, match="dated occupants"):
        migrate.downgrade(JOBS_REVISION)
    assert _version(db_path) == BILLING_REGRESSION_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM contract_occupancies")
    migrate.downgrade(JOBS_REVISION)
    schema = _schema(db_path)
    assert "contract_occupancies" not in schema and "billing_objections" not in schema
    assert "removal_date" not in schema["meters"] and "final_document" not in schema["utility_statements"]
    with sqlite3.connect(db_path) as conn:   # the rows survive the round trip
        assert conn.execute("SELECT id, balance FROM utility_statements").fetchall() == [("s1", -1400)]
    migrate()
    assert {"contract_occupancies", "billing_objections"} <= set(_schema(db_path))


REVERSALS_REVISION = "f3b9c1d7e2a5"


def _seed_bookings(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO accounts (id, portfolio_id, name, account_type, opening_balance, balance, created_at,
                                  updated_at) VALUES ('acc', 'pf', 'Konto', 'bank', 0, 0, '2025-01-01', '2025-01-01');
            INSERT INTO bookings (id, account_id, booking_date, amount, status, created_at, updated_at)
                VALUES ('b1', 'acc', '2026-02-03', 633.33, 'booked', '2026-02-03', '2026-02-03');
        """)


def test_booking_reversal_upgrade_keeps_bookings_and_downgrade_keeps_links(migrate):
    db_path = migrate(BILLING_REGRESSION_REVISION)
    _seed_previous_schema(db_path)
    _seed_bookings(db_path)
    migrate(REVERSALS_REVISION)
    assert "reverses_booking_id" in _schema(db_path)["bookings"]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, amount, reverses_booking_id FROM bookings").fetchall() == [
            ("b1", 633.33, None)]
        assert "idx_bookings_reverses" in {row[1] for row in conn.execute("PRAGMA index_list(bookings)")}
        conn.execute("INSERT INTO bookings (id, account_id, booking_date, amount, status, reverses_booking_id, "
                     "created_at, updated_at) VALUES ('r1', 'acc', '2026-02-10', -633.33, 'booked', 'b1', "
                     "'2026-02-10', '2026-02-10')")
    # the older program would count the reversal as an expense of its own
    with pytest.raises(RuntimeError, match="reversals exist"):
        migrate.downgrade(BILLING_REGRESSION_REVISION)
    assert _version(db_path) == REVERSALS_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM bookings WHERE id = 'r1'")
    migrate.downgrade(BILLING_REGRESSION_REVISION)
    assert "reverses_booking_id" not in _schema(db_path)["bookings"]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id FROM bookings").fetchall() == [("b1",)]
    migrate()
    assert "reverses_booking_id" in _schema(db_path)["bookings"]


def test_booking_reversal_downgrade_of_an_adopted_database_leaves_the_column(migrate):
    """create_all() writes the reference as a table constraint that SQLite cannot drop."""
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    migrate()
    migrate.downgrade(BILLING_REGRESSION_REVISION)
    assert _version(migrate.db_path) == BILLING_REGRESSION_REVISION
    assert "reverses_booking_id" in _schema(migrate.db_path)["bookings"]   # unused, ignored by older versions
    migrate()
    assert _version(migrate.db_path) == migrate.head


PROJECTS_REVISION = "b6d4f1a8c2e7"
PROJECT_TABLES = {"maintenance_work_packages", "maintenance_dependencies", "maintenance_participants",
                  "maintenance_quotes", "maintenance_orders", "maintenance_change_orders",
                  "maintenance_order_invoices", "invoice_payments", "maintenance_protocols",
                  "maintenance_appointments", "maintenance_case_documents"}


def _seed_project(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO maintenance_cases (id, property_id, title, priority, status, created_at, updated_at)
                VALUES ('mc', 'pr', 'Dachschaden', 'high', 'open', '2026-01-01', '2026-01-01');
            INSERT INTO maintenance_work_packages (id, case_id, title, kind, status, sort_order, created_at,
                                                   updated_at)
                VALUES ('wa', 'mc', 'Gerüst', 'work', 'planned', 0, '2026-01-01', '2026-01-01'),
                       ('wb', 'mc', 'Dach', 'work', 'planned', 1, '2026-01-01', '2026-01-01');
            INSERT INTO maintenance_dependencies (id, case_id, predecessor_id, successor_id, created_at)
                VALUES ('d1', 'mc', 'wa', 'wb', '2026-01-01');
        """)


def test_maintenance_project_upgrade_keeps_cases_and_downgrade_refuses_to_drop_projects(migrate):
    db_path = migrate(REVERSALS_REVISION)
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO maintenance_cases (id, property_id, title, priority, status, created_at, "
                     "updated_at) VALUES ('old', 'pr', 'Alter Fall', 'low', 'open', '2025-01-01', '2025-01-01')")
    migrate(PROJECTS_REVISION)
    schema = _schema(db_path)
    assert PROJECT_TABLES <= set(schema)
    assert {"case_id", "predecessor_id", "successor_id"} <= schema["maintenance_dependencies"]
    _seed_project(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert conn.execute("SELECT id, title FROM maintenance_cases ORDER BY id").fetchall() == [
            ("mc", "Dachschaden"), ("old", "Alter Fall")]
        with pytest.raises(sqlite3.IntegrityError):    # no self-dependency, no duplicate
            conn.execute("INSERT INTO maintenance_dependencies (id, case_id, predecessor_id, successor_id, "
                         "created_at) VALUES ('d2', 'mc', 'wa', 'wa', '2026-01-01')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO maintenance_dependencies (id, case_id, predecessor_id, successor_id, "
                         "created_at) VALUES ('d3', 'mc', 'wa', 'wb', '2026-01-01')")
        conn.execute("INSERT INTO documents (id, property_id, title, file_url, created_at, updated_at) "
                     "VALUES ('doc', 'pr', 'Protokoll', '/uploads/x.pdf', '2026-01-01', '2026-01-01')")
        conn.execute("INSERT INTO maintenance_protocols (id, case_id, protocol_type, protocol_date, defects, "
                     "photo_ids, status, document_id, content_sha256, created_at, updated_at) VALUES ('p1', 'mc', "
                     "'acceptance', '2026-06-01', '[]', '[]', 'final', 'doc', 'abc', '2026-01-01', '2026-01-01')")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE maintenance_protocols SET notes = 'x' WHERE id = 'p1'")
        with pytest.raises(sqlite3.IntegrityError):    # a final protocol always names its evidence
            conn.execute("INSERT INTO maintenance_protocols (id, case_id, protocol_type, protocol_date, defects, "
                         "photo_ids, status, created_at, updated_at) VALUES ('p2', 'mc', 'acceptance', "
                         "'2026-06-01', '[]', '[]', 'final', '2026-01-01', '2026-01-01')")
    with pytest.raises(RuntimeError, match="Maintenance project records exist"):
        migrate.downgrade(REVERSALS_REVISION)
    assert _version(db_path) == PROJECTS_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM maintenance_protocols")
        conn.execute("DELETE FROM maintenance_cases WHERE id = 'mc'")    # cascades through the project
        assert conn.execute("SELECT count(*) FROM maintenance_work_packages").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM maintenance_dependencies").fetchone() == (0,)
    migrate.downgrade(REVERSALS_REVISION)
    assert not PROJECT_TABLES & set(_schema(db_path))
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id FROM maintenance_cases").fetchall() == [("old",)]
    migrate()
    assert PROJECT_TABLES <= set(_schema(db_path)) and _version(db_path) == migrate.head


def test_maintenance_project_tables_of_a_create_all_database_are_adopted_with_the_guard(migrate):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(migrate.db_path) as conn:
        conn.execute("DROP TRIGGER immo_maintenance_protocols_final")
    migrate()
    assert _missing_from(_schema(migrate.db_path)) == {}
    with sqlite3.connect(migrate.db_path) as conn:
        triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert "immo_maintenance_protocols_final" in triggers


HANDOVER_REVISION = "a4d8e2f6c1b9"
HANDOVER_TRIGGERS = {"immo_handover_protocols_update", "immo_handover_protocols_delete"} | {
    f"immo_{table}_final_{operation}" for table in ("handover_rooms", "handover_keys", "handover_photos",
                                                    "meter_readings", "handover_defects")
    for operation in ("update", "delete")}


def _triggers(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


def _seed_handover(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO handover_protocols (id, contract_id, unit_id, protocol_type, protocol_date, tenant_present,
                                            landlord_present, key_count, damages, status, created_at, updated_at)
                VALUES ('hp', 'c1', 'u1', 'move_out', '2025-06-30', 1, 1, 3, 'Kratzer', 'finalized',
                        '2025-06-30', '2025-06-30');
            INSERT INTO meter_readings (id, handover_id, meter_type, reading_value, unit, created_at, updated_at)
                VALUES ('mr', 'hp', 'cold_water', 130, 'm³', '2025-06-30', '2025-06-30');
        """)


def test_handover_upgrade_keeps_protocols_editable_and_guards_finalized_ones(migrate):
    db_path = migrate(REVERSALS_REVISION)
    _seed_previous_schema(db_path)
    _seed_handover(db_path)
    migrate(HANDOVER_REVISION)
    schema = _schema(db_path)
    assert {"handover_rooms", "handover_defects", "handover_keys", "handover_photos"} <= set(schema)
    assert {"correction_of_id", "document_id", "finalized_at", "finalized_by"} <= schema["handover_protocols"]
    assert {"meter_id", "standalone_reading_id", "position"} <= schema["meter_readings"]
    assert HANDOVER_TRIGGERS <= _triggers(db_path)
    with sqlite3.connect(db_path) as conn:
        # a status "finalized" set by hand is no archived original: the row stays as it was and editable
        assert conn.execute("SELECT status, finalized_at, damages FROM handover_protocols").fetchall() == [
            ("finalized", None, "Kratzer")]
        conn.execute("UPDATE handover_protocols SET notes = 'nachgetragen'")
        conn.execute("INSERT INTO handover_rooms (id, protocol_id, position, name, created_at, updated_at) "
                     "VALUES ('r1', 'hp', 0, 'Bad', '2025-06-30', '2025-06-30')")
        conn.execute("UPDATE handover_protocols SET finalized_at = '2025-07-01'")
        for statement in ("UPDATE handover_protocols SET notes = 'x'", "DELETE FROM handover_rooms",
                          "UPDATE meter_readings SET reading_value = 1"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(statement)
    with pytest.raises(RuntimeError, match="Handover protocol data exists"):
        migrate.downgrade(PROJECTS_REVISION)
    assert _version(db_path) == HANDOVER_REVISION


def test_handover_downgrade_without_data_and_upgrade_again(migrate):
    db_path = migrate(REVERSALS_REVISION)
    _seed_previous_schema(db_path)
    _seed_handover(db_path)
    migrate(HANDOVER_REVISION)
    migrate.downgrade(PROJECTS_REVISION)
    schema = _schema(db_path)
    assert not {"handover_rooms", "handover_defects", "handover_keys", "handover_photos"} & set(schema)
    assert "finalized_at" not in schema["handover_protocols"] and "meter_id" not in schema["meter_readings"]
    assert not HANDOVER_TRIGGERS & _triggers(db_path)
    with sqlite3.connect(db_path) as conn:      # the older rows survive the round trip
        assert conn.execute("SELECT id, damages FROM handover_protocols").fetchall() == [("hp", "Kratzer")]
        assert conn.execute("SELECT id, reading_value FROM meter_readings").fetchall() == [("mr", 130)]
    migrate()
    assert _version(db_path) == migrate.head
    assert _missing_from(_schema(db_path)) == {}


def test_handover_downgrade_of_an_adopted_database_leaves_the_reference_columns(migrate):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)       # installs the triggers through the metadata event
    engine.dispose()
    assert HANDOVER_TRIGGERS <= _triggers(migrate.db_path)
    migrate()
    migrate.downgrade(PROJECTS_REVISION)
    schema = _schema(migrate.db_path)
    assert {"correction_of_id", "document_id"} <= schema["handover_protocols"]       # table-level references
    assert "finalized_at" not in schema["handover_protocols"]
    migrate()
    assert _version(migrate.db_path) == migrate.head
    assert _missing_from(_schema(migrate.db_path)) == {}


SERVICE_CONTRACTS_REVISION = "5e8b2d4f7a19"
SERVICE_CONTRACT_TABLES = {"service_contracts", "service_contract_locations", "service_contract_tariffs",
                           "service_contract_invoices", "service_contract_payments", "service_contract_documents"}


def _seed_service_contract(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO contacts (id, contact_type, company_name, country) VALUES ('sw', 'supplier', 'Stadtwerke', 'DE');
            INSERT INTO service_contracts (id, contract_type, title, provider_contact_id, start_date)
                VALUES ('sc', 'electricity', 'Allgemeinstrom', 'sw', '2026-01-01');
            INSERT INTO service_contract_locations (id, service_contract_id, property_id) VALUES ('loc', 'sc', 'pr');
            INSERT INTO invoices (id, supplier, invoice_date, net_amount, vat_amount, gross_amount, status, created_at,
                                  updated_at)
                VALUES ('inv', 'Stadtwerke', '2027-01-10', 100, 0, 100, 'open', '2027-01-10', '2027-01-10');
            INSERT INTO service_contract_invoices (id, service_contract_id, invoice_id, period_start, period_end)
                VALUES ('bill', 'sc', 'inv', '2026-01-01', '2026-12-31');
        """)


def test_service_contracts_upgrade_constraints_and_guarded_downgrade(migrate):
    db_path = migrate(REVERSALS_REVISION)
    _seed_previous_schema(db_path)
    _seed_bookings(db_path)
    migrate(SERVICE_CONTRACTS_REVISION)
    schema = _schema(db_path)
    assert SERVICE_CONTRACT_TABLES <= set(schema) and "service_contract_invoice_id" in schema["cost_items"]
    with sqlite3.connect(db_path) as conn:   # existing costs have no origin
        assert conn.execute("SELECT id, service_contract_invoice_id FROM cost_items").fetchall() == [("ci", None)]
    _seed_service_contract(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        defaults = conn.execute("SELECT renewal_mode, notice_to, reminder_days, recoverable, recoverable_percent "
                                "FROM service_contracts").fetchone()
        assert defaults == ("none", "term_end", 30, 0, 100)
        with pytest.raises(sqlite3.IntegrityError):    # a bill belongs to one contract
            conn.execute("INSERT INTO service_contract_invoices (id, service_contract_id, invoice_id, period_start, "
                         "period_end) VALUES ('bill2', 'sc', 'inv', '2026-01-01', '2026-12-31')")
        conn.execute("INSERT INTO service_contract_tariffs (id, service_contract_id, valid_from) "
                     "VALUES ('t1', 'sc', '2026-01-01')")
        with pytest.raises(sqlite3.IntegrityError):    # one tariff per contract and day
            conn.execute("INSERT INTO service_contract_tariffs (id, service_contract_id, valid_from) "
                         "VALUES ('t2', 'sc', '2026-01-01')")
        conn.execute("INSERT INTO service_contract_payments (id, service_contract_id, booking_id, amount) "
                     "VALUES ('p1', 'sc', 'b1', 10)")
        with pytest.raises(sqlite3.IntegrityError):    # a booking once per contract
            conn.execute("INSERT INTO service_contract_payments (id, service_contract_id, booking_id, amount) "
                         "VALUES ('p2', 'sc', 'b1', 5)")
        conn.execute("UPDATE cost_items SET service_contract_invoice_id = 'bill'")
        with pytest.raises(sqlite3.IntegrityError):    # a bill reaches a billing period once
            conn.execute("INSERT INTO cost_items (id, billing_period_id, description, amount, allocation_key_id, "
                         "is_recoverable, service_contract_invoice_id, created_at, updated_at) VALUES ('ci2', 'bp', "
                         "'x', 1, 'k', 1, 'bill', '2027-01-10', '2027-01-10')")
        with pytest.raises(sqlite3.IntegrityError):    # a provider in use stays in the address book
            conn.execute("DELETE FROM contacts WHERE id = 'sw'")
    # the older program would drop contracts and the origin of transferred costs
    with pytest.raises(RuntimeError, match="service contracts"):
        migrate.downgrade(HANDOVER_REVISION)
    assert _version(db_path) == SERVICE_CONTRACTS_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM service_contracts")         # cascades to locations, tariffs, bills, payments
        assert conn.execute("SELECT COUNT(*) FROM service_contract_locations").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM service_contract_payments").fetchone() == (0,)
    with pytest.raises(RuntimeError, match="transferred"):
        migrate.downgrade(HANDOVER_REVISION)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE cost_items SET service_contract_invoice_id = NULL")
    migrate.downgrade(HANDOVER_REVISION)
    schema = _schema(db_path)
    assert not SERVICE_CONTRACT_TABLES & set(schema) and "service_contract_invoice_id" not in schema["cost_items"]
    with sqlite3.connect(db_path) as conn:    # the rows survive the round trip
        assert conn.execute("SELECT id, amount FROM cost_items").fetchall() == [("ci", 400)]
    migrate()
    assert SERVICE_CONTRACT_TABLES <= set(_schema(db_path)) and _version(db_path) == migrate.head


def test_service_contracts_on_an_adopted_database(migrate):
    """create_all() already made the tables, the column and the index: upgrade and downgrade pass."""
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    migrate()
    assert SERVICE_CONTRACT_TABLES <= set(_schema(migrate.db_path))
    migrate.downgrade(HANDOVER_REVISION)
    schema = _schema(migrate.db_path)
    assert not SERVICE_CONTRACT_TABLES & set(schema) and "service_contract_invoice_id" not in schema["cost_items"]
    migrate()
    assert _version(migrate.db_path) == migrate.head



DEPOSITS_REVISION = "3c7e9a1d5f20"
DEPOSIT_TABLES = {"deposit_instalments", "deposit_interest_rates", "deposit_payments", "deposit_settlements",
                  "deposit_settlement_items"}


def test_deposit_file_upgrade_keeps_deposits_and_guards_the_downgrade(migrate):
    db_path = migrate(SERVICE_CONTRACTS_REVISION)
    _seed_previous_schema(db_path)
    _seed_bookings(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO deposits (id, contract_id, amount, status, held_date, created_at, updated_at) "
                     "VALUES ('d1', 'c1', 1500, 'held', '2020-01-01', '2025-01-01', '2025-01-01')")
    migrate(DEPOSITS_REVISION)
    schema = _schema(db_path)
    assert DEPOSIT_TABLES <= set(schema) and {"form", "cap_reason", "account_id", "released_on"} <= schema["deposits"]
    with sqlite3.connect(db_path) as conn:      # an existing deposit becomes a transfer without anything else
        assert conn.execute("SELECT id, amount, status, form, account_id FROM deposits").fetchall() == [
            ("d1", 1500, "held", "transfer", None)]
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO deposit_instalments (id, deposit_id, number, due_date, amount) "
                     "VALUES ('i1', 'd1', 1, '2020-01-01', 1500)")
        for statement in ("INSERT INTO deposit_instalments (id, deposit_id, number, due_date, amount) "
                          "VALUES ('i2', 'd1', 4, '2020-01-01', 1)",                    # at most three
                          "INSERT INTO deposit_payments (id, deposit_id, booking_id, kind, amount) "
                          "VALUES ('p0', 'd1', 'b1', 'receipt', 0)"):                   # a share is never zero
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
        conn.execute("INSERT INTO deposit_payments (id, deposit_id, booking_id, kind, amount) "
                     "VALUES ('p1', 'd1', 'b1', 'receipt', 633.33)")
        with pytest.raises(sqlite3.IntegrityError):    # a booking once per deposit
            conn.execute("INSERT INTO deposit_payments (id, deposit_id, booking_id, kind, amount) "
                         "VALUES ('p2', 'd1', 'b1', 'receipt', 1)")
        with pytest.raises(sqlite3.IntegrityError):    # the booking of a deposit stays
            conn.execute("DELETE FROM bookings WHERE id = 'b1'")
        conn.execute("INSERT INTO deposit_settlements (id, deposit_id, kind, settlement_date) "
                     "VALUES ('s1', 'd1', 'final', '2026-06-30')")
        conn.execute("UPDATE deposit_settlements SET finalized_at = '2026-07-01' WHERE id = 's1'")
        for statement in ("UPDATE deposit_settlements SET notes = 'x'", "DELETE FROM deposit_payments",
                          "UPDATE deposits SET amount = 1", "DELETE FROM deposit_instalments"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(statement)
        conn.execute("UPDATE deposits SET status = 'returned'")      # the state may still change
    with pytest.raises(RuntimeError, match="deposit file data exists"):
        migrate.downgrade(SERVICE_CONTRACTS_REVISION)
    assert _version(db_path) == DEPOSITS_REVISION


def test_deposit_file_downgrade_without_data_and_upgrade_again(migrate):
    db_path = migrate(SERVICE_CONTRACTS_REVISION)
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO deposits (id, contract_id, amount, status, created_at, updated_at) "
                     "VALUES ('d1', 'c1', 900, 'held', '2025-01-01', '2025-01-01')")
    migrate(DEPOSITS_REVISION)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE deposits SET form = 'guarantee'")
    with pytest.raises(RuntimeError, match="agreement details"):
        migrate.downgrade(SERVICE_CONTRACTS_REVISION)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE deposits SET form = 'transfer'")
    migrate.downgrade(SERVICE_CONTRACTS_REVISION)
    schema = _schema(db_path)
    assert not DEPOSIT_TABLES & set(schema) and "form" not in schema["deposits"]
    assert not {name for name in _triggers(db_path) if "deposit" in name}
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, amount FROM deposits").fetchall() == [("d1", 900)]
    migrate()
    assert _version(db_path) == migrate.head and _missing_from(_schema(db_path)) == {}


def test_deposit_file_on_an_adopted_database(migrate):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)       # installs the triggers through the metadata event
    engine.dispose()
    assert "immo_deposit_settlements_update" in _triggers(migrate.db_path)
    migrate()
    migrate.downgrade(SERVICE_CONTRACTS_REVISION)
    assert not DEPOSIT_TABLES & set(_schema(migrate.db_path))
    migrate()
    assert _version(migrate.db_path) == migrate.head


TAKEOVER_REVISION = "981b2631e1e8"


def test_contract_takeover_upgrade_keeps_contracts_and_guards_the_downgrade(migrate):
    db_path = migrate(DEPOSITS_REVISION)
    _seed_previous_schema(db_path)
    migrate(TAKEOVER_REVISION)
    assert {"ledger_start", "carried_balance"} <= _schema(db_path)["contracts"]
    with sqlite3.connect(db_path) as conn:      # existing tenancies keep their full account
        assert conn.execute("SELECT id, ledger_start, carried_balance FROM contracts").fetchall() == [("c1", None, None)]
        conn.execute("UPDATE contracts SET ledger_start = '2026-01-01', carried_balance = 250.5")
    with pytest.raises(RuntimeError, match="takeover date or carried balance"):
        migrate.downgrade(DEPOSITS_REVISION)
    assert _version(db_path) == TAKEOVER_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE contracts SET ledger_start = NULL, carried_balance = NULL")
    triggers = _triggers(db_path)
    migrate.downgrade(DEPOSITS_REVISION)
    assert not {"ledger_start", "carried_balance"} & _schema(db_path)["contracts"]
    assert _triggers(db_path) == triggers      # dropped in place: the table keeps its triggers
    migrate(TAKEOVER_REVISION)
    assert {"ledger_start", "carried_balance"} <= _schema(db_path)["contracts"]


ASSISTANT_REVISION = "f019a1b2c001"
DEPOSIT_TAKEOVER_REVISION = "a7d3c5e9f2b1"
DEPOSIT_TAKEOVER_COLUMNS = {"carried_on", "carried_amount", "carried_interest", "carried_note"}


def test_deposit_takeover_upgrade_guards_settled_deposits_and_the_downgrade(migrate):
    db_path = migrate(ASSISTANT_REVISION)
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO deposits (id, contract_id, amount, status, held_date, created_at, updated_at)
                VALUES ('d1', 'c1', 1500, 'held', '2020-01-01', '2025-01-01', '2025-01-01');
            INSERT INTO deposits (id, contract_id, amount, status, held_date, created_at, updated_at)
                VALUES ('d2', 'c1', 600, 'held', '2021-01-01', '2025-01-01', '2025-01-01');
            INSERT INTO deposit_settlements (id, deposit_id, kind, settlement_date, finalized_at)
                VALUES ('s1', 'd1', 'final', '2026-06-30', '2026-07-01');
        """)
    migrate(DEPOSIT_TAKEOVER_REVISION)
    assert DEPOSIT_TAKEOVER_COLUMNS <= _schema(db_path)["deposits"]
    with sqlite3.connect(db_path) as conn:      # existing deposits are not taken over by the update
        assert conn.execute("SELECT id, carried_on, carried_amount FROM deposits ORDER BY id").fetchall() == [
            ("d1", None, None), ("d2", None, None)]
        for statement in ("UPDATE deposits SET carried_amount = 1500 WHERE id = 'd1'",
                          "UPDATE deposits SET amount = 1 WHERE id = 'd1'"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(statement)
        conn.execute("UPDATE deposits SET carried_note = 'Vermerk', status = 'returned' WHERE id = 'd1'")
        conn.execute("UPDATE deposits SET carried_on = '2025-01-01', carried_amount = 600 WHERE id = 'd2'")
    with pytest.raises(RuntimeError, match="takeover of deposits"):
        migrate.downgrade(ASSISTANT_REVISION)
    assert _version(db_path) == DEPOSIT_TAKEOVER_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE deposits SET carried_note = NULL WHERE id = 'd1'")      # the note is not guarded
        conn.execute("UPDATE deposits SET carried_on = NULL, carried_amount = NULL WHERE id = 'd2'")
    triggers = _triggers(db_path)
    migrate.downgrade(ASSISTANT_REVISION)
    assert not DEPOSIT_TAKEOVER_COLUMNS & _schema(db_path)["deposits"]
    assert _triggers(db_path) == triggers       # the earlier guard is back, the others untouched
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE deposits SET amount = 1 WHERE id = 'd1'")
    migrate(DEPOSIT_TAKEOVER_REVISION)
    assert DEPOSIT_TAKEOVER_COLUMNS <= _schema(db_path)["deposits"]


def test_deposit_takeover_on_an_adopted_database(migrate):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)       # the columns and the extended guard exist already
    engine.dispose()
    migrate()
    assert _version(migrate.db_path) == migrate.head and _missing_from(_schema(migrate.db_path)) == {}
    with sqlite3.connect(migrate.db_path) as conn:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'immo_deposits_settled_update'").fetchone()[0]
    assert "carried_amount" in sql


@pytest.mark.parametrize("previous", ["f020a1b2c001", "a7d3c5e9f2b1"])
def test_history_and_deposit_branches_merge_without_rewriting_retained_data(migrate, previous):
    db_path = migrate(previous)
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO change_history (id,entity_type,entity_id,field_name,new_value,changed_at) "
                     "VALUES ('old-history','property','pr','name','Unveränderter Bestand','2000-01-01')")
        conn.execute("INSERT INTO deposits (id,contract_id,amount,status,held_date,created_at,updated_at) "
                     "VALUES ('retained-deposit','c1',1500,'held','2000-01-01','2000-01-01','2000-01-01')")
        if previous == DEPOSIT_TAKEOVER_REVISION:
            conn.execute("UPDATE deposits SET carried_on='2000-01-01',carried_amount=1500")
    migrate()
    assert _version(db_path) == "f021a1b2c001"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT new_value FROM change_history WHERE id='old-history'").fetchone()[0] == "Unveränderter Bestand"
        assert conn.execute("SELECT amount,carried_amount FROM deposits WHERE id='retained-deposit'").fetchone() == (
            1500, 1500 if previous == DEPOSIT_TAKEOVER_REVISION else None)
        assert "idx_change_history_cursor" in {row[1] for row in conn.execute("PRAGMA index_list(change_history)")}
        conn.execute("UPDATE deposits SET carried_on='2000-01-01',carried_amount=1500")
    with pytest.raises(RuntimeError, match="takeover of deposits"):
        migrate.downgrade(ASSISTANT_REVISION)
    with sqlite3.connect(db_path) as conn:
        # Refuse before SQLite could drop the other branch's index permanently.
        assert "idx_change_history_cursor" in {row[1] for row in conn.execute("PRAGMA index_list(change_history)")}
        assert conn.execute("SELECT carried_amount FROM deposits WHERE id='retained-deposit'").fetchone()[0] == 1500
    assert _version(db_path) == "f021a1b2c001"
