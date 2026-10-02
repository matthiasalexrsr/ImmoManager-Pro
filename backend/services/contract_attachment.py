"""Freeze managed local source bytes in bounded chunks, never fetch remote URLs."""

import hashlib
import os
import stat
from contextlib import contextmanager
from urllib.parse import urlparse

from ..config import settings
from ..storage import ValidationError
from .file_storage import LocalStorage, get_file_storage

CHUNK_BYTES = 64 * 1024


def fingerprint(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@contextmanager
def local_source(file_url):
    from ..routers.files import _file_url_to_key
    parsed = urlparse(file_url)
    if parsed.scheme or not file_url.startswith(("/uploads/", "uploads/")):
        raise ValidationError("Anlage besitzt nur einen externen Verweis. Bitte lokal hochladen oder ausdrücklich als reinen Metadatenverweis wählen.")
    storage = get_file_storage()
    if not isinstance(storage, LocalStorage):
        raise ValidationError("Diese Anlage ist nicht lokal verfügbar. Bitte lokal hochladen oder ausdrücklich nur Metadaten verknüpfen.")
    key = _file_url_to_key(file_url)
    try:
        path = storage._path(key)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValidationError("Anlage ist keine reguläre lokale Datei.")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            before = fingerprint(os.fstat(stream.fileno()))
            before_path = fingerprint(path.stat())
            if before[:3] != before_path[:3]:
                raise ValidationError("Die Anlage wurde während der Prüfung ausgetauscht. Bitte erneut prüfen.")
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValidationError("Anlage ist keine reguläre lokale Datei.")
            yield stream
            # Windows may expose different timestamp caches for a file handle
            # and path. Compare each API with its own prior observation, while
            # requiring the same device/inode/size across both observations.
            if before != fingerprint(os.fstat(stream.fileno())) or before_path != fingerprint(path.stat()):
                raise ValidationError("Die Anlage wurde während der Prüfung geändert. Bitte erneut prüfen.")
    except ValidationError:
        raise
    except (OSError, ValueError):
        raise ValidationError("Anlage ist nicht verfügbar. Bitte erneut hochladen oder bewusst nur Metadaten verknüpfen.") from None


def capture(file_url, *, on_chunk=None):
    digest = hashlib.sha256()
    size = 0
    with local_source(file_url) as source:
        position = 0
        while True:
            chunk = source.read(CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.max_upload_size_bytes:
                raise ValidationError("Anlage überschreitet das konfigurierte technische Uploadbudget. Budget anpassen, Datei aufteilen oder ausdrücklich nur Metadaten verknüpfen.")
            digest.update(chunk)
            if on_chunk:
                on_chunk(position, chunk)
            position += 1
    return {"sha256": digest.hexdigest(), "size_bytes": size, "mode": "frozen_bytes"}
