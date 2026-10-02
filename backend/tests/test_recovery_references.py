"""Bounded synthetic SQLite checks: no application data, archives, or restores."""

import hashlib
import json
import shutil
import sqlite3
import time
from contextlib import closing

import pytest

from backend.services.recovery_archive import RecoveryError
from backend.services.recovery_validation import rebase_file_references, validate_file_references


def _database(tmp_path, values, *, column="file_url", name="refs.db"):
    database = tmp_path / name
    with closing(sqlite3.connect(database)) as db:
        # Deliberately no id column: file references cannot depend on domain IDs.
        db.execute(f'CREATE TABLE documents ("{column}" TEXT, note TEXT)')
        db.executemany(f'INSERT INTO documents ("{column}", note) VALUES (?, ?)', [(value, f"note-{i}") for i, value in enumerate(values)])
        db.commit()
    return database


def _rows(database, query="SELECT * FROM documents"):
    with closing(sqlite3.connect(database)) as db:
        return db.execute(query).fetchall()


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("reference", [
    "uploads/documents/proof.pdf",
    "/uploads/documents/proof.pdf",
    "documents/proof.pdf",
    "/api/v1/files/download?key=documents%2Fproof.pdf",
    "/api/files/download?key=documents%2Fproof.pdf&download=1",
    "uploads\\documents\\proof.pdf",
])
def test_relative_and_api_references_prove_actual_file_coverage_readonly(tmp_path, reference):
    uploads = tmp_path / "uploads"
    (uploads / "documents").mkdir(parents=True)
    (uploads / "documents" / "proof.pdf").write_bytes(b"synthetic document")
    database = _database(tmp_path, [reference])
    before = _hash(database)
    report = validate_file_references(database, str(uploads))
    assert report.local_references == 1
    assert report.local_files == frozenset({"documents/proof.pdf"})
    assert report.external_reference_count == 0
    assert rebase_file_references(database, str(uploads)) == 0
    assert _hash(database) == before


@pytest.mark.parametrize("column", ["file_url", "receipt_url", "file_path", "document_url", "document_path", "receipt_path", "storage_key", "ocr_url", "photo_url"])
def test_every_supported_reference_column_is_checked(tmp_path, column):
    database = _database(tmp_path, ["uploads/missing.pdf"], column=column)
    with pytest.raises(RecoveryError, match="fehlt"):
        validate_file_references(database, str(tmp_path / "uploads"), expected_upload_files=set())


@pytest.mark.parametrize("reference", [
    "uploads/missing.pdf", "/uploads/missing.pdf", "/api/v1/files/download?key=missing.pdf",
])
def test_missing_tree_or_wrong_empty_manifest_is_rejected(tmp_path, reference):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    database = _database(tmp_path, [reference])
    with pytest.raises(RecoveryError, match="fehlt"):
        validate_file_references(database, str(uploads))
    with pytest.raises(RecoveryError, match="fehlt"):
        validate_file_references(database, str(uploads), expected_upload_files=set())


def test_staging_coverage_uses_archived_keys_even_when_source_file_exists(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "proof.pdf").write_bytes(b"source is present")
    database = _database(tmp_path, [str(uploads / "proof.pdf")])
    before = _hash(database)
    with pytest.raises(RecoveryError, match="fehlt"):
        rebase_file_references(database, str(uploads), tmp_path / "unpublished", expected_upload_files={"different.pdf"})
    assert _hash(database) == before


def test_mixed_absolute_roots_cannot_be_covered_by_matching_basenames(tmp_path):
    uploads = tmp_path / "selected" / "uploads"
    other = tmp_path / "legacy" / "uploads"
    database = _database(tmp_path, [str(uploads / "proof.pdf"), str(other / "proof.pdf")])
    with pytest.raises(RecoveryError, match="ausserhalb"):
        validate_file_references(database, str(uploads), expected_upload_files={"proof.pdf"})


@pytest.mark.parametrize("reference", [
    "https://user:private@example.invalid/document.pdf?token=private",
    "http://example.invalid/uploads/proof.pdf",
    "s3://synthetic-bucket/documents/proof.pdf",
])
def test_external_urls_remain_external_without_exposing_them_in_report(tmp_path, reference):
    database = _database(tmp_path, [reference])
    report = validate_file_references(database, str(tmp_path / "uploads"), expected_upload_files=set())
    assert report.local_references == 0
    assert report.local_files == frozenset()
    assert report.external_reference_count == 1
    assert "private" not in repr(report)
    assert rebase_file_references(database, str(tmp_path / "uploads"), tmp_path / "new", expected_upload_files=set()) == 0
    assert _rows(database)[0][0] == reference


@pytest.mark.parametrize("key", ["https://example.invalid/proof.pdf", "s3://bucket/proof.pdf", "uploads/../proof.pdf", "/proof.pdf", "C:/uploads/proof.pdf"])
def test_external_or_invalid_manifest_tree_is_rejected(tmp_path, key):
    database = _database(tmp_path, [])
    with pytest.raises(RecoveryError):
        validate_file_references(database, str(tmp_path / "uploads"), expected_upload_files={key})


@pytest.mark.parametrize("reference", [
    "/uploads/../private.pdf",
    "uploads/%2e%2e/private.pdf",
    "/api/v1/files/download?key=..%2Fprivate.pdf",
    "/api/v1/files/download?key=proof.pdf&key=other.pdf",
    "/api/v1/files/download?key=",
    "/api/v1/other?key=proof.pdf",
    "javascript:alert(1)",
    "https:///missing-host.pdf",
    "C:relative.pdf",
    "uploads/folder//proof.pdf",
])
def test_ambiguous_unsafe_or_unsupported_local_reference_is_rejected(tmp_path, reference):
    database = _database(tmp_path, [reference])
    with pytest.raises(RecoveryError):
        validate_file_references(database, str(tmp_path / "uploads"), expected_upload_files={"proof.pdf"})


def test_windows_absolute_paths_rebase_in_a_synthetic_portable_catalog(tmp_path):
    root = r"C:\Synthetic\Uploads"
    database = _database(tmp_path, [r"c:\synthetic\uploads\Documents\PROOF.pdf", "uploads/Documents/PROOF.pdf", "file:///C:/Synthetic/Uploads/documents/proof.pdf"])
    destination = tmp_path / "unpublished" / "uploads"
    assert rebase_file_references(database, root, destination, expected_upload_files={"documents/proof.pdf"}) == 3
    assert _rows(database) == [
        (str(destination / "documents" / "proof.pdf"), "note-0"),
        ("/uploads/documents/proof.pdf", "note-1"),
        (str(destination / "documents" / "proof.pdf"), "note-2"),
    ]
    assert not destination.exists()


@pytest.mark.parametrize("reference", [r"D:\Synthetic\Uploads\proof.pdf", r"C:\Synthetic\Other\proof.pdf", r"C:\Synthetic\Uploads\..\private.pdf"])
def test_windows_outside_tree_paths_are_rejected(tmp_path, reference):
    database = _database(tmp_path, [reference])
    with pytest.raises(RecoveryError):
        validate_file_references(database, r"C:\Synthetic\Uploads", expected_upload_files={"proof.pdf"})


def test_manifest_case_collision_is_rejected(tmp_path):
    database = _database(tmp_path, ["uploads/proof.pdf"])
    with pytest.raises(RecoveryError, match="kollidieren"):
        validate_file_references(database, str(tmp_path / "uploads"), expected_upload_files={"proof.pdf", "PROOF.pdf"})


def test_directory_and_symlink_are_not_backed_up_regular_files(tmp_path):
    uploads = tmp_path / "uploads"
    (uploads / "directory.pdf").mkdir(parents=True)
    database = _database(tmp_path, ["uploads/directory.pdf"])
    with pytest.raises(RecoveryError, match="keine Datei"):
        validate_file_references(database, str(uploads))
    external = tmp_path / "outside.pdf"
    external.write_bytes(b"outside upload tree")
    try:
        (uploads / "link.pdf").symlink_to(external)
    except OSError:
        pytest.skip("Creating synthetic symlinks is not permitted on this host")
    with closing(sqlite3.connect(database)) as db:
        db.execute("UPDATE documents SET file_url='uploads/link.pdf'")
        db.commit()
    with pytest.raises(RecoveryError, match="Symlink|Reparsepunkt"):
        validate_file_references(database, str(uploads))


def test_file_url_blobs_do_not_silently_skip_coverage(tmp_path):
    database = _database(tmp_path, [b"uploads/proof.pdf"])
    with pytest.raises(RecoveryError, match="Nichttextueller"):
        validate_file_references(database, str(tmp_path / "uploads"), expected_upload_files={"proof.pdf"})


def test_handover_photo_list_checks_every_url_and_preserves_external_values(tmp_path):
    root = tmp_path / "uploads"
    photo_values = [str(root / "photo.jpg"), "/uploads/other.jpg", "https://example.invalid/external.jpg"]
    database = _database(tmp_path, [json.dumps(photo_values)], column="photos")
    with pytest.raises(RecoveryError, match="fehlt"):
        validate_file_references(database, str(root), expected_upload_files={"photo.jpg"})
    report = validate_file_references(database, str(root), expected_upload_files={"photo.jpg", "other.jpg"})
    assert (report.local_references, report.external_reference_count) == (2, 1)
    destination = tmp_path / "new"
    assert rebase_file_references(database, str(root), destination, expected_upload_files={"photo.jpg", "other.jpg"}) == 1
    assert json.loads(_rows(database)[0][0]) == [str(destination / "photo.jpg"), *photo_values[1:]]


@pytest.mark.parametrize("photos", ["not json", "{}", '["uploads/proof.pdf", 1]', '[""]'])
def test_malformed_photo_collections_fail_closed(tmp_path, photos):
    database = _database(tmp_path, [photos], column="photos")
    with pytest.raises(RecoveryError):
        validate_file_references(database, str(tmp_path / "uploads"), expected_upload_files={"proof.pdf"})


def test_rebase_modifies_only_synthetic_copy_and_keeps_business_data(tmp_path):
    root, destination = tmp_path / "source-uploads", tmp_path / "new-uploads"
    source = _database(tmp_path, [str(root / "proof.pdf"), "uploads/proof.pdf", "/api/v1/files/download?key=proof.pdf", "s3://bucket/object.pdf"])
    before = _hash(source)
    staged = tmp_path / "staged.db"
    shutil.copy2(source, staged)
    assert rebase_file_references(staged, str(root), destination, expected_upload_files={"proof.pdf"}) == 1
    assert _hash(source) == before
    assert _rows(staged) == [(str(destination / "proof.pdf"), "note-0"), ("uploads/proof.pdf", "note-1"), ("/api/v1/files/download?key=proof.pdf", "note-2"), ("s3://bucket/object.pdf", "note-3")]


def test_real_sqlite_sentinel_triggers_are_suspended_and_restored(tmp_path):
    root, destination = tmp_path / "source-uploads", tmp_path / "new-uploads"
    source = _database(tmp_path, [str(root / "proof.pdf")])
    with closing(sqlite3.connect(source)) as db:
        db.executescript("""
            CREATE TABLE sentinel (counter INTEGER, payload BLOB);
            INSERT INTO sentinel VALUES (7, X'00ff');
            CREATE TABLE auth_setup (marker TEXT PRIMARY KEY);
            INSERT INTO auth_setup VALUES ('first-owner-closed');
            CREATE TABLE audit (message TEXT);
            INSERT INTO audit VALUES ('existing business audit');
            CREATE TRIGGER path_before BEFORE UPDATE OF file_url ON documents BEGIN
                UPDATE sentinel SET counter=counter+1, payload=X'bad0';
                DELETE FROM auth_setup;
            END;
            CREATE TRIGGER path_after AFTER UPDATE OF file_url ON documents BEGIN
                INSERT INTO audit VALUES ('trigger actually fired');
            END;
        """)
        triggers = db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY rowid").fetchall()
    before = _hash(source)
    staged = tmp_path / "staged.db"
    shutil.copy2(source, staged)
    assert rebase_file_references(staged, str(root), destination, expected_upload_files={"proof.pdf"}) == 1
    assert _hash(source) == before
    assert _rows(staged, "SELECT * FROM sentinel") == [(7, b"\x00\xff")]
    assert _rows(staged, "SELECT * FROM auth_setup") == [("first-owner-closed",)]
    assert _rows(staged, "SELECT * FROM audit") == [("existing business audit",)]
    assert _rows(staged, "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY rowid") == triggers
    # Demonstrate actual trigger preservation, rather than merely a schema match.
    with closing(sqlite3.connect(staged)) as db:
        db.execute("UPDATE documents SET file_url=?", (str(destination / "proof.pdf"),))
        db.commit()
    assert _rows(staged, "SELECT * FROM sentinel") == [(8, b"\xba\xd0")]
    assert _rows(staged, "SELECT * FROM auth_setup") == []
    assert _rows(staged, "SELECT * FROM audit")[-1] == ("trigger actually fired",)


def test_full_row_comparison_rejects_independent_foreign_key_cascade(tmp_path):
    root, destination = tmp_path / "source-uploads", tmp_path / "new-uploads"
    database = tmp_path / "cascade.db"
    with closing(sqlite3.connect(database)) as db:
        db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE documents (file_path TEXT PRIMARY KEY);
            CREATE TABLE business (sentinel TEXT REFERENCES documents(file_path) ON UPDATE CASCADE, amount INTEGER);
        """)
        db.execute("INSERT INTO documents VALUES (?)", (str(root / "proof.pdf"),))
        db.execute("INSERT INTO business VALUES (?, ?)", (str(root / "proof.pdf"), 900))
        db.commit()
    before = _hash(database)
    with pytest.raises(RecoveryError, match="nicht genehmigte Geschaeftsdaten"):
        rebase_file_references(database, str(root), destination, expected_upload_files={"proof.pdf"})
    assert _hash(database) == before
    assert _rows(database, "SELECT * FROM business") == [(str(root / "proof.pdf"), 900)]


def test_sql_failure_rolls_back_path_and_trigger_schema(tmp_path):
    root, destination = tmp_path / "source-uploads", tmp_path / "new-uploads"
    database = tmp_path / "constraint.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE documents(file_path TEXT CHECK(file_path=?))".replace("?", "'" + str(root / "proof.pdf").replace("'", "''") + "'"))
        db.execute("INSERT INTO documents VALUES (?)", (str(root / "proof.pdf"),))
        db.executescript("CREATE TABLE sentinel(value INTEGER); INSERT INTO sentinel VALUES(1); CREATE TRIGGER path_guard AFTER UPDATE ON documents BEGIN UPDATE sentinel SET value=2; END;")
        db.commit()
        triggers = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger'").fetchall()
    before = _hash(database)
    with pytest.raises(RecoveryError, match="nicht sicher"):
        rebase_file_references(database, str(root), destination, expected_upload_files={"proof.pdf"})
    assert _hash(database) == before
    assert _rows(database, "SELECT sql FROM sqlite_master WHERE type='trigger'") == triggers
    assert _rows(database, "SELECT * FROM sentinel") == [(1,)]


def test_without_rowid_and_duplicate_values_are_all_rebased(tmp_path):
    root, destination = tmp_path / "source-uploads", tmp_path / "new-uploads"
    database = tmp_path / "composite.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE documents(code TEXT PRIMARY KEY, file_path TEXT, amount INTEGER) WITHOUT ROWID")
        db.executemany("INSERT INTO documents VALUES (?, ?, ?)", [("a", str(root / "proof.pdf"), 10), ("b", str(root / "proof.pdf"), 20)])
        db.commit()
    assert rebase_file_references(database, str(root), destination, expected_upload_files={"proof.pdf"}) == 2
    assert _rows(database, "SELECT * FROM documents ORDER BY code") == [("a", str(destination / "proof.pdf"), 10), ("b", str(destination / "proof.pdf"), 20)]


def test_expired_caller_deadline_refuses_changes(tmp_path):
    root = tmp_path / "uploads"
    database = _database(tmp_path, [str(root / "proof.pdf")])
    before = _hash(database)
    with pytest.raises(RecoveryError, match="Zeitlimit"):
        rebase_file_references(database, str(root), tmp_path / "new", expected_upload_files={"proof.pdf"}, deadline=time.monotonic() - 1)
    assert _hash(database) == before
