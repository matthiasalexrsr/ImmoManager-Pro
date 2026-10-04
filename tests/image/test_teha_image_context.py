"""Prepared real SQLite context cases; Root alone executes the native gate.

Reuse the existing explicit-key crypto/original fixture. No new product import,
factory, runtime bootstrap, path, private image, provider or test conftest.
Fixture writes and memory ATTACH precede the caller's read-only transaction.
"""

import pytest
from test_teha_receive_image import ImageFixture, TehaImageError


@pytest.fixture
def context_image():
    image = ImageFixture()
    try:
        yield image
    finally:
        image.db.close()


def _quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _attach_memory(image, alias):
    image.db.execute(f"ATTACH DATABASE ? AS {_quoted(alias)}", (":memory:",))
    assert image.db.execute(
        "SELECT name,file FROM pragma_database_list WHERE name=?", (alias,),
    ).fetchone() == (alias, "")
    return _quoted(alias)


def _original_rows(image):
    rows = []
    for query in (
        "SELECT id,metadata_snapshot,sha256,size_bytes FROM main.document_versions ORDER BY id",
        "SELECT version_id,position,data FROM main.document_version_chunks ORDER BY version_id,position",
    ):
        cursor = image.db.execute(query)
        try:
            rows.append(tuple(cursor.fetchall()))
        finally:
            cursor.close()
    return tuple(rows)


def _assert_readonly_validation(image, *, error_code=None):
    assert image.db.in_transaction
    assert image.db.execute("PRAGMA query_only").fetchone()[0] == 1
    assert image.db.execute("PRAGMA trusted_schema").fetchone()[0] == 0
    before_changes, before_originals = image.db.total_changes, _original_rows(image)
    statements = []
    image.db.set_trace_callback(statements.append)
    report = None
    try:
        if error_code is None:
            report = image.validate()
        else:
            with pytest.raises(TehaImageError) as refused:
                image.validate()
            assert refused.value.code == error_code and str(refused.value) == error_code
    finally:
        image.db.set_trace_callback(None)
        assert image.db.total_changes == before_changes and image.db.in_transaction
        assert image.db.execute("PRAGMA query_only").fetchone()[0] == 1
        assert image.db.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        assert _original_rows(image) == before_originals
        assert statements
        # SQLite may prefix internal pragma traces with "-- ". Those traces
        # must still describe read-only operations, never setup or mutation.
        operations = [sql.lstrip().removeprefix("-- ").lstrip().split()[0].upper() for sql in statements]
        assert set(operations) <= {"SELECT", "PRAGMA"}
    return report


def _assert_original_report(report):
    assert report.family_present
    assert (report.mappings, report.receipts, report.document_receipts, report.task_receipts) == (1, 1, 1, 0)
    assert not report.command_digest_reconstructed


def test_ascii_temp_index_alias_of_relevant_main_index_is_refused(context_image):
    image = context_image
    image.db.execute("CREATE TEMP TABLE context_index_source (unrelated_value INTEGER)")
    image.db.execute(
        'CREATE INDEX temp."IX_TEHA_MAPPING_LOOKUP" ON context_index_source(unrelated_value)',
    )
    assert image.db.execute(
        "SELECT name,tbl_name FROM main.sqlite_schema WHERE type='index' AND name='ix_teha_mapping_lookup'",
    ).fetchone() == ("ix_teha_mapping_lookup", "teha_external_mappings")
    assert image.db.execute(
        "SELECT name,tbl_name FROM temp.sqlite_schema WHERE type='index' AND name='IX_TEHA_MAPPING_LOOKUP'",
    ).fetchone() == ("IX_TEHA_MAPPING_LOOKUP", "context_index_source")
    assert tuple(row[2] for row in image.db.execute('PRAGMA main.index_info("ix_teha_mapping_lookup")')) == (
        "connection_key", "kind", "external_identity_hash", "generation",
    )
    assert tuple(row[2] for row in image.db.execute('PRAGMA index_info("ix_teha_mapping_lookup")')) == (
        "unrelated_value",
    )
    image.seal()
    _assert_readonly_validation(image, error_code="TEHA_IMAGE_CONTEXT_REQUIRED")


def test_missing_main_period_parent_supplied_by_quoted_attach_is_refused(context_image):
    image = context_image
    image.mapping(
        "CONTEXT-PERIOD", "period", {"object_id": 41, "period_number": 7},
        "PERIOD", "mapping-run", image.property_row,
    )
    alias = _attach_memory(image, 'Incoming "ArChIvE"')
    image.db.execute(f'CREATE TABLE {alias}."BiLlInG_PeRiOdS" (id VARCHAR PRIMARY KEY, property_id VARCHAR NOT NULL)')
    image.db.execute(f'INSERT INTO {alias}."BiLlInG_PeRiOdS" VALUES (?,?)', ("PERIOD", "PROP"))
    image.db.execute("DROP TABLE main.billing_periods")
    assert image.db.execute(
        "SELECT COUNT(*) FROM main.sqlite_schema WHERE type='table' AND name='billing_periods'",
    ).fetchone()[0] == 0
    assert image.db.execute(f'SELECT id,property_id FROM {alias}."BiLlInG_PeRiOdS"').fetchall() == [("PERIOD", "PROP")]
    assert image.db.execute("SELECT id,property_id FROM billing_periods").fetchall() == [("PERIOD", "PROP")]
    image.seal()
    _assert_readonly_validation(image, error_code="TEHA_IMAGE_CONTEXT_REQUIRED")
    assert image.db.execute(f'SELECT id,property_id FROM {alias}."BiLlInG_PeRiOdS"').fetchall() == [("PERIOD", "PROP")]


def test_same_named_attach_relation_with_existing_main_remains_compatible(context_image):
    image = context_image
    alias = _attach_memory(image, 'Other "MAIN" Image')
    image.db.execute(f'CREATE TABLE {alias}."PrOpErTiEs" (id VARCHAR PRIMARY KEY, portfolio_id VARCHAR NOT NULL)')
    image.db.execute(f'INSERT INTO {alias}."PrOpErTiEs" VALUES (?,?)', ("PROP", "OTHER"))
    assert image.db.execute("SELECT portfolio_id FROM main.properties WHERE id='PROP'").fetchone()[0] == "P"
    assert image.db.execute(f'SELECT portfolio_id FROM {alias}."PrOpErTiEs" WHERE id=?', ("PROP",)).fetchone()[0] == "OTHER"
    assert image.db.execute("SELECT portfolio_id FROM properties WHERE id='PROP'").fetchone()[0] == "P"
    image.seal()
    _assert_original_report(_assert_readonly_validation(image))
    assert image.db.execute(f'SELECT portfolio_id FROM {alias}."PrOpErTiEs" WHERE id=?', ("PROP",)).fetchone()[0] == "OTHER"


def test_unrelated_temp_and_quoted_attach_objects_remain_compatible(context_image):
    image = context_image
    image.db.execute("CREATE TEMP TABLE context_notes (value VARCHAR)")
    image.db.execute("CREATE INDEX temp.context_notes_index ON context_notes(value)")
    image.db.execute("CREATE TEMP VIEW context_note_view AS SELECT value FROM context_notes")
    image.db.execute("INSERT INTO temp.context_notes VALUES (?)", ("temporary fixture note",))
    alias = _attach_memory(image, 'Notes "Only"')
    image.db.execute(f"CREATE TABLE {alias}.context_archive_notes (value VARCHAR)")
    image.db.execute(f"INSERT INTO {alias}.context_archive_notes VALUES (?)", ("attached fixture note",))
    image.seal()
    _assert_original_report(_assert_readonly_validation(image))
    assert image.db.execute("SELECT value FROM temp.context_note_view").fetchall() == [("temporary fixture note",)]
    assert image.db.execute(f"SELECT value FROM {alias}.context_archive_notes").fetchall() == [("attached fixture note",)]


def test_more_than_513_unrelated_catalog_objects_remain_compatible(context_image):
    image = context_image
    for number in range(514):
        name = f"context_stock_{number:04}"
        image.db.execute(f'CREATE TABLE main."{name}" (value INTEGER)')
        image.db.execute(f'CREATE INDEX main."{name}_index" ON "{name}"(value)')
    counts = dict(image.db.execute(
        "SELECT type,COUNT(*) FROM main.sqlite_schema WHERE name GLOB 'context_stock_*' GROUP BY type",
    ).fetchall())
    assert counts == {"table": 514, "index": 514} and sum(counts.values()) > 513
    image.seal()
    _assert_original_report(_assert_readonly_validation(image))
    assert dict(image.db.execute(
        "SELECT type,COUNT(*) FROM main.sqlite_schema WHERE name GLOB 'context_stock_*' GROUP BY type",
    ).fetchall()) == counts
