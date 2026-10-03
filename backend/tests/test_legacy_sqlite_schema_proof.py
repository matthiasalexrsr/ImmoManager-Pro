import re
import sqlite3
from contextlib import closing

import pytest

from backend.legacy_sqlite_upgrade.schema import (
    LegacySchemaError,
    catalog,
    catalog_hash,
    inspect_legacy_sqlite,
    normalized_table_sql,
    profiles,
    prove_legacy_schema,
)


@pytest.fixture(params=tuple(profiles()))
def legacy(request, tmp_path):
    path = tmp_path / "synthetic-126.sqlite"
    reference = profiles()[request.param]
    with closing(sqlite3.connect(path)) as connection:
        for sql in reference["ddl"]:
            connection.execute(sql)
        connection.commit()
    return path, request.param, reference


def test_complete_profile_reproves_exact_catalog_and_later_omissions(legacy):
    path, name, reference = legacy
    before = path.read_bytes()
    proof = inspect_legacy_sqlite(path)
    assert proof.profile_id == name
    assert proof.schema_sha256 == reference["schema_sha256"]
    assert proof.permits_missing("allocation_keys", {"consumption_medium", "consumption_unit"})
    assert not proof.permits_missing("users", {"totp_secret"})
    assert not proof.permits_missing("unknown", {"id"})
    with closing(sqlite3.connect(path)) as connection:
        proof.verify(connection)
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["guard", "foreign_key", "index", "check", "partial_family", "extra_table", "stamp", "marker_trigger"])
def test_full_detection_refuses_unknown_or_weakened_schema_without_repair(legacy, damage):
    path, _, _ = legacy
    with closing(sqlite3.connect(path)) as connection:
        if damage == "guard":
            name = connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%lifecycle%' LIMIT 1").fetchone()[0]
            connection.execute('DROP TRIGGER "' + name + '"')
            connection.execute('CREATE TRIGGER "' + name + '" BEFORE DELETE ON contract_lifecycle_commands BEGIN SELECT 1; END')
        elif damage in {"foreign_key", "check"}:
            sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='payments'").fetchone()[0]
            changed = sql.replace("RESTRICT", "CASCADE", 1) if damage == "foreign_key" else sql.replace("receivable_id", "rent_charge_id", 1)
            assert changed != sql
            connection.execute("PRAGMA writable_schema=ON")
            connection.execute("UPDATE sqlite_master SET sql=? WHERE name='payments'", (changed,))
            connection.execute("PRAGMA writable_schema=OFF")
        elif damage == "index":
            connection.execute("DROP INDEX idx_payments_booking")
            connection.execute("CREATE INDEX idx_payments_booking ON payments(id DESC)")
        elif damage == "partial_family":
            connection.execute("DROP TABLE contract_lifecycle_commands")
        elif damage == "extra_table":
            connection.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
        elif damage == "stamp":
            connection.execute("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            connection.execute("INSERT INTO alembic_version VALUES ('z1a2b3c4d5e6')")
        else:
            connection.execute("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            connection.execute("CREATE TRIGGER injected_marker AFTER INSERT ON alembic_version BEGIN UPDATE portfolios SET name='Injected changed state'; END")
        connection.commit()
    before = path.read_bytes()
    with pytest.raises((LegacySchemaError, sqlite3.DatabaseError)):
        inspect_legacy_sqlite(path)
    assert path.read_bytes() == before


def test_stale_or_fabricated_proof_is_not_an_archive_bypass(legacy):
    path, _, _ = legacy
    proof = inspect_legacy_sqlite(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE INDEX foreign_extra ON users(username)")
        connection.commit()
        assert catalog_hash(catalog(connection)) != proof.schema_sha256
        with pytest.raises(LegacySchemaError):
            proof.verify(connection)
        with pytest.raises(LegacySchemaError):
            prove_legacy_schema(connection)


def test_constraint_declaration_order_has_identical_complete_native_proof(legacy, tmp_path):
    _, name, reference = legacy
    path = tmp_path / "same-native-constraints-different-order.sqlite"
    changed = 0
    with closing(sqlite3.connect(path)) as connection:
        for sql in reference["ddl"]:
            reordered = _reverse_table_constraints(sql)
            changed += reordered != sql
            assert normalized_table_sql(reordered) == normalized_table_sql(sql)
            connection.execute(reordered)
        connection.commit()
    assert changed > 0
    assert inspect_legacy_sqlite(path).profile_id == name


def _reverse_table_constraints(sql):
    # Preserve raw column/default definitions and all non-table objects. Native
    # PRAGMA defaults retain their SQL spelling; only table constraint order is
    # deliberately permuted to model SQLAlchemy's independent constraint set.
    if not sql.lstrip().upper().startswith("CREATE TABLE"):
        return sql
    tokens = re.finditer(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[(?:[^\]])*\]|[(),]", sql)
    start = next(token.end() for token in tokens if token.group() == "(")
    depth, position, pieces = 0, start, []
    for token in tokens:
        value = token.group()
        if value == ")" and depth == 0:
            pieces.append(sql[position:token.start()])
            end = token.start()
            break
        if value == "," and depth == 0:
            pieces.append(sql[position:token.start()])
            position = token.end()
        else:
            depth += (value == "(") - (value == ")")
    kinds = {"constraint", "primary", "foreign", "unique", "check"}
    columns = [piece for piece in pieces if piece.split()[0].lower() not in kinds]
    constraints = [piece for piece in pieces if piece.split()[0].lower() in kinds]
    return sql[:start] + ",".join(columns + list(reversed(constraints))) + sql[end:]
