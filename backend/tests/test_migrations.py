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
        migrate.downgrade(REVERSALS_REVISION)
    assert _version(db_path) == SERVICE_CONTRACTS_REVISION
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM service_contracts")         # cascades to locations, tariffs, bills, payments
        assert conn.execute("SELECT COUNT(*) FROM service_contract_locations").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM service_contract_payments").fetchone() == (0,)
    with pytest.raises(RuntimeError, match="transferred"):
        migrate.downgrade(REVERSALS_REVISION)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE cost_items SET service_contract_invoice_id = NULL")
    migrate.downgrade(REVERSALS_REVISION)
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
    migrate.downgrade(REVERSALS_REVISION)
    schema = _schema(migrate.db_path)
    assert not SERVICE_CONTRACT_TABLES & set(schema) and "service_contract_invoice_id" not in schema["cost_items"]
    migrate()
    assert _version(migrate.db_path) == migrate.head

