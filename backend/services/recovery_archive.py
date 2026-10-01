"""Streaming authenticated envelope for full-recovery ZIP archives."""

import hashlib
import math
import os
import struct
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, cast
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"IMMOFULL1"
HEADER_SIZE = len(MAGIC) + 16 + 12
CHUNK = 1024 * 1024
_EOCD = struct.Struct("<4s4H2IH")
_ZIP64_LOCATOR = struct.Struct("<4sIQI")
_ZIP64_END = struct.Struct("<4sQ2H2I4Q")
_CENTRAL = struct.Struct("<4s6H3I5H2I")
_LOCAL = struct.Struct("<4s5H3I2H")
_UINT32_MAX = 0xFFFFFFFF


class RecoveryError(ValueError):
    """Recovery was rejected; no existing installation was replaced."""


def check_zip_budget(path: Path, *, maximum_entries: int, maximum_directory_bytes: int,
                     timeout_seconds: float) -> None:
    """Bound ZIP metadata before ZipFile allocates its directory/ZipInfo list.

    This accepts the single-disk, non-prefixed ZIP/ZIP64 format emitted by our
    seekless writer. It validates structure/bounds, not member CRCs or names;
    authenticated decryption and the normal recovery checks remain required.
    Record layouts follow PKWARE APPNOTE sections 4.3.7 and 4.3.12-4.3.16.
    Memory use is independent of the directory size/count: a 65 KiB tail and
    one extra field of at most 65 KiB, rather than a ZipInfo for each member.
    """
    if (type(maximum_entries) is not int or maximum_entries <= 0
            or type(maximum_directory_bytes) is not int or maximum_directory_bytes <= 0
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise RecoveryError("ZIP-Prüfgrenzen müssen positiv und endlich sein.")
    deadline = time.monotonic() + timeout_seconds

    def check_time():
        if time.monotonic() >= deadline:
            raise RecoveryError("ZIP-Verzeichnisprüfung hat das Zeitlimit überschritten.")

    def read_at(stream, offset: int, amount: int, boundary: int) -> bytes:
        check_time()
        if offset < 0 or amount < 0 or offset + amount > boundary:
            raise RecoveryError("Ungültige ZIP-Record-/Offsetgrenzen.")
        stream.seek(offset)
        data = stream.read(amount)
        if len(data) != amount:
            raise RecoveryError("ZIP-Datei ist unvollständig oder wurde verändert.")
        check_time()
        return data

    def identity(info):
        return info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev

    with path.open("rb") as stream:
        initial = identity(os.fstat(stream.fileno()))
        size = initial[0]
        if size < _EOCD.size:
            raise RecoveryError("ZIP-Endverzeichnis fehlt.")
        tail_start = max(0, size - _EOCD.size - 65535)
        tail = read_at(stream, tail_start, size - tail_start, size)
        search_end = len(tail)
        while True:
            check_time()
            position = tail.rfind(b"PK\x05\x06", 0, search_end)
            if position < 0:
                raise RecoveryError("ZIP-Endverzeichnis fehlt oder ist beschädigt.")
            if position + _EOCD.size <= len(tail):
                end = _EOCD.unpack_from(tail, position)
                if position + _EOCD.size + end[7] == len(tail):
                    break
            search_end = position
        end_offset = tail_start + position
        _, disk, directory_disk, disk_entries, declared_entries, directory_bytes, directory_offset, _ = end
        if disk != 0 or directory_disk != 0 or disk_entries != declared_entries:
            raise RecoveryError("Mehrteilige ZIP-Archive werden nicht unterstützt.")
        directory_end = end_offset
        locator_offset = end_offset - _ZIP64_LOCATOR.size
        locator = read_at(stream, locator_offset, _ZIP64_LOCATOR.size, end_offset) if locator_offset >= 0 else b""
        if locator.startswith(b"PK\x06\x07"):
            _, locator_disk, zip64_offset, disks = _ZIP64_LOCATOR.unpack(locator)
            if locator_disk != 0 or disks != 1:
                raise RecoveryError("Mehrteilige ZIP64-Archive werden nicht unterstützt.")
            record = _ZIP64_END.unpack(read_at(stream, zip64_offset, _ZIP64_END.size, locator_offset))
            signature, record_bytes, _, _, disk64, directory_disk64, disk_entries64, entries64, bytes64, offset64 = record
            if signature != b"PK\x06\x06" or record_bytes < _ZIP64_END.size - 12 or zip64_offset + 12 + record_bytes != locator_offset:
                raise RecoveryError("Ungültige ZIP64-Endverzeichnisgrenzen.")
            if disk64 != 0 or directory_disk64 != 0 or disk_entries64 != entries64:
                raise RecoveryError("Mehrteilige ZIP64-Archive werden nicht unterstützt.")
            for small, large, marker in ((declared_entries, entries64, 0xFFFF),
                                         (directory_bytes, bytes64, _UINT32_MAX),
                                         (directory_offset, offset64, _UINT32_MAX)):
                if small != marker and small != large:
                    raise RecoveryError("ZIP- und ZIP64-Verzeichnisse widersprechen sich.")
            declared_entries, directory_bytes, directory_offset = entries64, bytes64, offset64
            directory_end = zip64_offset
        elif directory_bytes == _UINT32_MAX or directory_offset == _UINT32_MAX:
            raise RecoveryError("Erforderliches ZIP64-Endverzeichnis fehlt.")
        if declared_entries > maximum_entries:
            raise RecoveryError("Zu viele ZIP-Archiveinträge.")
        if directory_bytes > maximum_directory_bytes:
            raise RecoveryError("ZIP-Verzeichnis überschreitet das Metadatenlimit.")
        if directory_offset < 0 or directory_offset + directory_bytes != directory_end:
            raise RecoveryError("Ungültige ZIP-Verzeichnis-/Offsetgrenzen.")
        cursor, count = directory_offset, 0
        while cursor < directory_end:
            header = _CENTRAL.unpack(read_at(stream, cursor, _CENTRAL.size, directory_end))
            if header[0] != b"PK\x01\x02":
                raise RecoveryError("Ungültiger ZIP-Verzeichniseintrag.")
            count += 1
            if count > maximum_entries:
                raise RecoveryError("Zu viele tatsächliche ZIP-Archiveinträge.")
            compressed, uncompressed = header[8:10]
            name_bytes, extra_bytes, comment_bytes, member_disk = header[10:14]
            member_offset = header[16]
            next_cursor = cursor + _CENTRAL.size + name_bytes + extra_bytes + comment_bytes
            if next_cursor > directory_end:
                raise RecoveryError("ZIP-Verzeichniseintrag überschreitet die Recordgrenzen.")
            extra = read_at(stream, cursor + _CENTRAL.size + name_bytes, extra_bytes, next_cursor)
            required = [(uncompressed == _UINT32_MAX, "Q"), (compressed == _UINT32_MAX, "Q"),
                        (member_offset == _UINT32_MAX, "Q"), (member_disk == 0xFFFF, "I")]
            values = [uncompressed, compressed, member_offset, member_disk]
            extra_cursor, found64 = 0, False
            while extra_cursor < len(extra):
                check_time()
                if len(extra) - extra_cursor < 4:
                    raise RecoveryError("Ungültiges ZIP-Extrafeld.")
                field, field_bytes = struct.unpack_from("<HH", extra, extra_cursor)
                field_start = extra_cursor + 4
                field_end = field_start + field_bytes
                if field_end > len(extra):
                    raise RecoveryError("Ungültige ZIP-Extrafeldgrenzen.")
                if field == 1:
                    if found64:
                        raise RecoveryError("Doppeltes ZIP64-Extrafeld.")
                    found64 = True
                    value_cursor = field_start
                    for index, (needed, format_code) in enumerate(required):
                        if needed:
                            value_bytes = struct.calcsize("<" + format_code)
                            if value_cursor + value_bytes > field_end:
                                raise RecoveryError("ZIP64-Extrafeld ist unvollständig.")
                            values[index] = struct.unpack_from("<" + format_code, extra, value_cursor)[0]
                            value_cursor += value_bytes
                extra_cursor = field_end
            if any(needed for needed, _ in required) and not found64:
                raise RecoveryError("Erforderliches ZIP64-Extrafeld fehlt.")
            _, compressed, member_offset, member_disk = values
            if member_disk != 0:
                raise RecoveryError("Mehrteilige ZIP-Archiveinträge werden nicht unterstützt.")
            local = _LOCAL.unpack(read_at(stream, member_offset, _LOCAL.size, directory_offset))
            if local[0] != b"PK\x03\x04" or local[2] != header[3] or local[3] != header[4]:
                raise RecoveryError("Ungültiger lokaler ZIP-Dateiheader.")
            data_end = member_offset + _LOCAL.size + local[9] + local[10] + compressed
            if data_end > directory_offset:
                raise RecoveryError("ZIP-Dateidaten überschreiten die Verzeichnisgrenze.")
            cursor = next_cursor
        if count != declared_entries:
            raise RecoveryError("Tatsächliche ZIP-Eintragsanzahl stimmt nicht mit dem Verzeichnis überein.")
        check_time()
        if identity(os.fstat(stream.fileno())) != initial or identity(path.stat()) != initial:
            raise RecoveryError("ZIP-Datei wurde während der Prüfung verändert.")


def _key(password: str, salt: bytes) -> bytes:
    if not isinstance(password, str) or len(password) < 12:
        raise RecoveryError("Die Sicherung erfordert eine Passphrase mit mindestens 12 Zeichen.")
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000, dklen=32)


class _EncryptedWriter:
    def __init__(self, stream, encryptor):
        self.stream, self.encryptor, self.position = stream, encryptor, 0

    def write(self, data):
        self.stream.write(self.encryptor.update(data))
        self.position += len(data)
        return len(data)

    def tell(self):
        return self.position

    def seek(self, *_args):
        raise OSError("Encrypted ZIP output is not seekable")

    def flush(self):
        self.stream.flush()


@contextmanager
def encrypted_zip(path: Path, password: str):
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    encryptor = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    with path.open("xb") as stream:
        stream.write(header)
        with ZipFile(cast(BinaryIO, _EncryptedWriter(stream, encryptor)), "w", ZIP_DEFLATED, allowZip64=True) as archive:
            yield archive
        stream.write(encryptor.finalize())
        stream.write(encryptor.tag)
        stream.flush()
        os.fsync(stream.fileno())


def decrypt_zip(source: Path, destination: Path, password: str, maximum_bytes: int):
    size = source.stat().st_size
    if size < HEADER_SIZE + 16 or size > maximum_bytes:
        raise RecoveryError("Sicherungsdatei ist unvollstaendig oder zu gross.")
    with source.open("rb") as stream:
        header = stream.read(HEADER_SIZE)
        if not header.startswith(MAGIC):
            raise RecoveryError("Unbekanntes Sicherungsformat.")
        salt, nonce = header[len(MAGIC):len(MAGIC) + 16], header[-12:]
        stream.seek(-16, 2)
        tag = stream.read(16)
        decryptor = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        stream.seek(HEADER_SIZE)
        remaining = size - HEADER_SIZE - 16
        try:
            with destination.open("xb") as output:
                while remaining:
                    block = stream.read(min(CHUNK, remaining))
                    if not block:
                        raise RecoveryError("Sicherungsdatei wurde waehrend des Lesens verkuerzt.")
                    remaining -= len(block)
                    output.write(decryptor.update(block))
                output.write(decryptor.finalize())
        except InvalidTag as exc:
            raise RecoveryError("Passphrase falsch oder Sicherungsdatei beschaedigt.") from exc
