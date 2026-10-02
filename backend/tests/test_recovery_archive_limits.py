"""Bound ZIP metadata using private synthetic archives before ZipFile parsing."""

import io
import itertools
import os
import struct
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest

from backend.services import recovery_archive as recovery

EOCD = struct.Struct("<4s4H2IH")
ZIP64_END = struct.Struct("<4sQ2H2I4Q")
ZIP64_LOCATOR = struct.Struct("<4sIQI")
CENTRAL = struct.Struct("<4s6H3I5H2I")


class SeeklessWriter:
    """The same non-seekable interface used by the encrypted archive writer."""

    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, value):
        return self.buffer.write(value)

    def tell(self):
        return self.buffer.tell()

    def seek(self, *_args):
        raise OSError("synthetic seekless output")

    def flush(self):
        pass


class TrackedReader:
    def __init__(self, stream, after_read):
        self.stream, self.after_read = stream, after_read

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def read(self, amount):
        data = self.stream.read(amount)
        self.after_read(amount)
        return data


def plain_archive(tmp_path, *, count=3, comment=b"", filename_length=0):
    path = tmp_path / "private-fixture.zip"
    with ZipFile(path, "w", ZIP_STORED) as archive:
        for index in range(count):
            item = ZipInfo(f"member-{index:03d}" + "x" * filename_length)
            item.comment = b"synthetic member comment"
            item.extra = struct.pack("<HH4s", 0xCAFE, 4, b"test")
            archive.writestr(item, b"synthetic data")
        archive.comment = comment
    return path


def zip64_archive(tmp_path, monkeypatch):
    import zipfile
    # Exercise actual stdlib ZIP64 end records and per-member size/offset extra
    # fields without allocating GiB files or tens of thousands of ZipInfo objects.
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 64)
    monkeypatch.setattr(zipfile, "ZIP_FILECOUNT_LIMIT", 2)
    output = SeeklessWriter()
    with ZipFile(output, "w", ZIP_STORED, allowZip64=True) as archive:
        for index, data in enumerate((b"x" * 100, b"y", b"z")):
            with archive.open(f"member-{index}", "w", force_zip64=True) as member:
                member.write(data)
    path = tmp_path / "private-seekless-zip64.zip"
    path.write_bytes(output.buffer.getvalue())
    assert b"PK\x06\x06" in path.read_bytes() and b"PK\x07\x08" in path.read_bytes()
    return path


def check(path, **options):
    recovery.check_zip_budget(path, maximum_entries=options.get("maximum_entries", 100),
                              maximum_directory_bytes=options.get("maximum_directory_bytes", 1024 * 1024),
                              timeout_seconds=options.get("timeout_seconds", 5))


def change_eocd(path, field, value):
    raw = bytearray(path.read_bytes())
    offset = raw.rfind(b"PK\x05\x06")
    fields = list(EOCD.unpack_from(raw, offset))
    fields[field] = value
    EOCD.pack_into(raw, offset, *fields)
    path.write_bytes(raw)


def central_offset(path):
    return path.read_bytes().find(b"PK\x01\x02")


def change_central(path, field, value):
    raw = bytearray(path.read_bytes())
    offset = central_offset(path)
    fields = list(CENTRAL.unpack_from(raw, offset))
    fields[field] = value
    CENTRAL.pack_into(raw, offset, *fields)
    path.write_bytes(raw)


def test_standard_zip_and_maximum_comment_are_accepted_and_still_readable(tmp_path):
    path = plain_archive(tmp_path, comment=b"c" * 65535)
    check(path)
    with ZipFile(path) as archive:
        assert len(archive.infolist()) == 3
        assert archive.read("member-000") == b"synthetic data"
        assert len(archive.comment) == 65535


def test_empty_zip_is_valid_metadata_and_is_left_for_manifest_validation(tmp_path):
    path = plain_archive(tmp_path, count=0)
    check(path, maximum_directory_bytes=1, maximum_entries=1)
    with ZipFile(path) as archive:
        assert archive.infolist() == []


def test_legitimate_seekless_zip64_is_accepted_including_data_descriptors(tmp_path, monkeypatch):
    path = zip64_archive(tmp_path, monkeypatch)
    check(path)
    with ZipFile(path) as archive:
        assert len(archive.infolist()) == 3
        assert archive.read("member-0") == b"x" * 100
        assert archive.read("member-1") == b"y"
        assert archive.read("member-2") == b"z"


def test_declared_count_over_budget_fails_before_any_zipfile_parser(tmp_path, monkeypatch):
    path = plain_archive(tmp_path, count=20)
    monkeypatch.setattr(recovery, "ZipFile", lambda *args, **kwargs: pytest.fail("Directory must be bounded before ZipFile"))
    with pytest.raises(recovery.RecoveryError, match="Zu viele"):
        check(path, maximum_entries=5)


def test_actual_many_tiny_entries_cannot_bypass_budget_with_false_declared_count(tmp_path, monkeypatch):
    path = plain_archive(tmp_path, count=40)
    change_eocd(path, 3, 1)
    change_eocd(path, 4, 1)
    monkeypatch.setattr(recovery, "ZipFile", lambda *args, **kwargs: pytest.fail("ZipFile must never run before the budget check"))
    with pytest.raises(recovery.RecoveryError, match="tatsächliche"):
        check(path, maximum_entries=5)


@pytest.mark.parametrize("declared", [0, 1, 4, 7])
def test_wrong_declared_count_is_rejected_even_when_both_counts_fit_budget(tmp_path, declared):
    path = plain_archive(tmp_path)
    change_eocd(path, 3, declared)
    change_eocd(path, 4, declared)
    with pytest.raises(recovery.RecoveryError, match="Eintragsanzahl"):
        check(path)


def test_large_directory_metadata_is_rejected_before_parser_allocation(tmp_path, monkeypatch):
    path = plain_archive(tmp_path, count=3, filename_length=1000)
    monkeypatch.setattr(recovery, "ZipFile", lambda *args, **kwargs: pytest.fail("No parser allocation for an oversized directory"))
    with pytest.raises(recovery.RecoveryError, match="Metadatenlimit"):
        check(path, maximum_directory_bytes=500)


def test_metadata_check_reads_bounded_chunks_without_scanning_large_member_data(tmp_path, monkeypatch):
    path = tmp_path / "large-payload.zip"
    with ZipFile(path, "w", ZIP_STORED) as archive:
        archive.writestr("large-member", b"x" * (2 * 1024 * 1024))
    requests = []
    original_open = Path.open

    def tracked_open(candidate, *args, **kwargs):
        stream = original_open(candidate, *args, **kwargs)
        return TrackedReader(stream, requests.append) if candidate == path else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(recovery, "ZipFile", lambda *args, **kwargs: pytest.fail("Budget check must not instantiate ZipFile"))
    check(path)
    assert requests and all(0 <= amount <= 65535 + EOCD.size for amount in requests)
    assert sum(requests) < 70 * 1024


def test_source_change_during_budget_check_is_rejected(tmp_path, monkeypatch):
    path = plain_archive(tmp_path)
    initial = path.stat()
    original_open = Path.open
    changed = []

    def change_source(_amount):
        if not changed:
            os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1_000_000_000))
            changed.append(True)

    def tracked_open(candidate, *args, **kwargs):
        stream = original_open(candidate, *args, **kwargs)
        return TrackedReader(stream, change_source) if candidate == path else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(recovery.RecoveryError, match="während der Prüfung verändert"):
        check(path)


@pytest.mark.parametrize("field,value", [(1, 1), (2, 1), (3, 2), (6, 0), (5, 0), (5, 0xFFFFFFFF), (6, 0xFFFFFFFF)])
def test_broken_end_record_disk_size_and_offset_bounds_are_rejected(tmp_path, field, value):
    path = plain_archive(tmp_path)
    change_eocd(path, field, value)
    with pytest.raises(recovery.RecoveryError):
        check(path)


@pytest.mark.parametrize("field,value", [(10, 65535), (11, 65535), (12, 65535), (13, 1), (16, 0xFFFFFFFE), (8, 0xFFFFFFFE)])
def test_member_record_disk_offset_size_and_variable_record_bounds_are_rejected(tmp_path, field, value):
    path = plain_archive(tmp_path)
    change_central(path, field, value)
    with pytest.raises(recovery.RecoveryError):
        check(path)


def test_local_offset_pointing_into_directory_is_rejected(tmp_path):
    path = plain_archive(tmp_path)
    change_central(path, 16, central_offset(path))
    with pytest.raises(recovery.RecoveryError, match="Offsetgrenzen"):
        check(path)


def test_local_data_range_overlapping_central_directory_is_rejected(tmp_path):
    path = plain_archive(tmp_path)
    change_central(path, 8, central_offset(path))
    with pytest.raises(recovery.RecoveryError, match="Dateidaten"):
        check(path)


@pytest.mark.parametrize("record,field,value", [("locator", 1, 1), ("locator", 2, 0xFFFFFFFFFFFFFFFF), ("locator", 3, 2),
                                               ("end", 1, 0), ("end", 1, 0xFFFFFFFFFFFFFFFF), ("end", 4, 1),
                                               ("end", 5, 1), ("end", 6, 99), ("end", 8, 0xFFFFFFFFFFFFFFFF),
                                               ("end", 9, 0xFFFFFFFFFFFFFFFF)])
def test_zip64_record_and_locator_bounds_are_not_trusted(tmp_path, monkeypatch, record, field, value):
    path = zip64_archive(tmp_path, monkeypatch)
    raw = bytearray(path.read_bytes())
    layout, signature = (ZIP64_LOCATOR, b"PK\x06\x07") if record == "locator" else (ZIP64_END, b"PK\x06\x06")
    offset = raw.rfind(signature)
    fields = list(layout.unpack_from(raw, offset))
    fields[field] = value
    layout.pack_into(raw, offset, *fields)
    path.write_bytes(raw)
    with pytest.raises(recovery.RecoveryError):
        check(path)


def test_zip64_false_count_cannot_bypass_actual_entry_count(tmp_path, monkeypatch):
    path = zip64_archive(tmp_path, monkeypatch)
    raw = bytearray(path.read_bytes())
    offset = raw.rfind(b"PK\x06\x06")
    fields = list(ZIP64_END.unpack_from(raw, offset))
    fields[6] = fields[7] = 1
    ZIP64_END.pack_into(raw, offset, *fields)
    path.write_bytes(raw)
    change_eocd(path, 3, 1)
    change_eocd(path, 4, 1)
    with pytest.raises(recovery.RecoveryError, match="Eintragsanzahl"):
        check(path)


@pytest.mark.parametrize("mutation", ["missing", "truncated"])
def test_required_zip64_member_fields_must_exist_and_fit_extra_record(tmp_path, monkeypatch, mutation):
    path = zip64_archive(tmp_path, monkeypatch)
    raw = bytearray(path.read_bytes())
    fields = CENTRAL.unpack_from(raw, central_offset(path))
    extra_offset = central_offset(path) + CENTRAL.size + fields[10]
    assert struct.unpack_from("<H", raw, extra_offset)[0] == 1
    struct.pack_into("<H", raw, extra_offset + (0 if mutation == "missing" else 2), 2 if mutation == "missing" else 8)
    path.write_bytes(raw)
    with pytest.raises(recovery.RecoveryError, match="ZIP64-Extrafeld"):
        check(path)


def test_truncated_or_appended_bytes_cannot_pass_end_record_bounds(tmp_path):
    path = plain_archive(tmp_path)
    original = path.read_bytes()
    for changed in (original[:-1], original + b"unexpected trailing data", b"not a zip", original[:20]):
        path.write_bytes(changed)
        with pytest.raises(recovery.RecoveryError):
            check(path)


def test_deadline_interrupts_streamed_directory_validation_without_zipfile_allocation(tmp_path, monkeypatch):
    path = plain_archive(tmp_path, count=20)
    clock = itertools.count()
    monkeypatch.setattr(recovery.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(recovery, "ZipFile", lambda *args, **kwargs: pytest.fail("Deadline failure must precede parser allocation"))
    with pytest.raises(recovery.RecoveryError, match="Zeitlimit"):
        check(path, timeout_seconds=12)


@pytest.mark.parametrize("options", [{"maximum_entries": 0}, {"maximum_entries": True}, {"maximum_directory_bytes": -1},
                                     {"maximum_directory_bytes": True}, {"timeout_seconds": 0},
                                     {"timeout_seconds": float("nan")}, {"timeout_seconds": float("inf")}])
def test_invalid_resource_limits_are_rejected_before_file_open(tmp_path, options):
    with pytest.raises(recovery.RecoveryError, match="Prüfgrenzen"):
        check(tmp_path / "does-not-exist.zip", **options)
