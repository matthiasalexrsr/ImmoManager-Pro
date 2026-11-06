"""Independent read-only demo count/isolation boundaries, without starting a GUI."""

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from backend.services.filesystem_paths import filesystem_path
from scripts import check_demo_runtime as smoke


@pytest.fixture
def dataset(tmp_path):
    data = tmp_path / "demo data Ä"
    data.mkdir()
    marker = {"schema": "immomanager-demo-bw/1", "database": "demo-bw.sqlite3", "state": "complete", "identity": "private-fixture"}
    (data / "immomanager-demo-bw.json").write_text(json.dumps(marker), encoding="utf-8")
    with closing(sqlite3.connect(data / "demo-bw.sqlite3")) as connection, connection:
        for table, count in smoke.MINIMUM_COUNTS.items():
            connection.execute('CREATE TABLE "' + table + '" (id INTEGER)')
            connection.executemany('INSERT INTO "' + table + '" VALUES (?)', ((index,) for index in range(count)))
    return data


def test_count_verification_reads_real_sqlite_rows_without_writing_the_database(dataset):
    before = hashlib.sha256((dataset / "demo-bw.sqlite3").read_bytes()).hexdigest()
    marker, counts = smoke.inspect_demo(dataset)
    assert marker["identity"] == "private-fixture"
    assert counts == smoke.MINIMUM_COUNTS
    assert hashlib.sha256((dataset / "demo-bw.sqlite3").read_bytes()).hexdigest() == before


def test_count_verification_supports_deep_unicode_and_fragment_character_paths(dataset,tmp_path):
    plain=tmp_path/('long-owned-demo-'*5)/('nested-'*12)/('Demo Ä # space '+'x'*60)
    deep=filesystem_path(plain)
    deep.mkdir(parents=True)
    for path in dataset.iterdir():
        shutil.copyfile(path,deep/path.name)
    database=deep/'demo-bw.sqlite3'
    before=hashlib.sha256(database.read_bytes()).hexdigest()
    marker,counts=smoke.inspect_demo(plain)
    assert marker['identity']=='private-fixture' and counts==smoke.MINIMUM_COUNTS
    assert hashlib.sha256(database.read_bytes()).hexdigest()==before


def test_self_reported_complete_marker_cannot_approve_an_empty_entity_table(dataset):
    with closing(sqlite3.connect(dataset / "demo-bw.sqlite3")) as connection, connection:
        connection.execute("DELETE FROM bookings")
    with pytest.raises(ValueError, match="independently counted"):
        smoke.inspect_demo(dataset)


def test_missing_or_unfinished_demo_cannot_create_or_adopt_a_database(dataset):
    marker = dataset / "immomanager-demo-bw.json"
    value = json.loads(marker.read_text())
    marker.write_text(json.dumps({**value, "state": "new"}))
    with pytest.raises(ValueError, match="complete bound marker"):
        smoke.inspect_demo(dataset)
    marker.write_text(json.dumps(value))
    (dataset / "demo-bw.sqlite3").unlink()
    with pytest.raises(ValueError, match="missing or linked"):
        smoke.inspect_demo(dataset)
    assert not (dataset / "demo-bw.sqlite3").exists()


def test_protected_file_inventory_detects_edits_and_new_files(tmp_path):
    file = tmp_path / "sentinel"
    file.write_bytes(b"synthetic operator data")
    before = smoke.inventory(tmp_path)
    file.write_bytes(b"changed")
    assert smoke.inventory(tmp_path) != before
    file.write_bytes(b"synthetic operator data")
    (tmp_path / "unexpected-key.json").write_text("generated in the wrong profile")
    assert smoke.inventory(tmp_path) != before


@pytest.mark.parametrize("platform,suffix", [("win32", "ImmoManager-Pro-CLI.exe"), ("linux", "ImmoManager-Pro-CLI"),
                                              ("darwin", "Contents/MacOS/ImmoManager-Pro-CLI")])
def test_demo_native_probe_uses_the_exact_companion_without_a_shell(tmp_path, monkeypatch, platform, suffix):
    folder = tmp_path / ("application.app" if platform == "darwin" else "native")
    cli = folder / suffix
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"native executable fixture; never executed")
    monkeypatch.setattr(smoke, "sys", SimpleNamespace(platform=platform))
    assert smoke.cli_command(SimpleNamespace(source=False, dist=folder)) == [str(cli)]
    cli.unlink()
    with pytest.raises(ValueError, match="missing"):
        smoke.cli_command(SimpleNamespace(source=False, dist=folder))
