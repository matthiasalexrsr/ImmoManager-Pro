"""File storage service abstraction.

Supports:
- LocalStorage (default): Files stored on local filesystem
- S3Storage: S3-compatible storage (AWS S3, MinIO)

Configure via FILE_STORAGE_BACKEND and S3_* environment variables.
"""

import hashlib
import logging
import os
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional

from .filesystem_paths import filesystem_path

logger = logging.getLogger(__name__)


class StorageUnavailable(RuntimeError):
    """Storage failed; this is not evidence that an original is absent."""


def validate_key(key: str) -> str:
    if (not key or key.startswith("/") or "\\" in key or ":" in key
            or any(part in ("", ".", "..") for part in key.split("/"))
            or any(ord(char) < 32 for char in key)):
        raise ValueError("Ungültiger Dateischlüssel")
    return key


class FileStorage(ABC):
    """Abstract interface for file storage."""

    @abstractmethod
    def save(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        """Save a file and return its URL/path."""
        ...

    @abstractmethod
    def get(self, key: str) -> Optional[bytes]:
        """Retrieve file contents by key."""
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a file by key."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a file exists."""
        ...

    @abstractmethod
    def get_url(self, key: str) -> str:
        """Get a URL/path for accessing the file."""
        ...


class LocalStorage(FileStorage):
    """Local filesystem storage.

    Files are stored under a configurable base directory.
    """

    def __init__(self, base_dir: str | Path | None = None):
        # By default the uploads folder the app serves under /uploads (the data folder): a
        # relative "uploads" followed the working directory, which the Windows program sets
        # to its own install folder, so uploaded documents could not be opened there.
        if base_dir is None:
            from ..paths import get_uploads_dir

            base_dir = get_uploads_dir()
        self.base_dir = Path(base_dir)
        filesystem_path(self.base_dir).mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        # Prevent path traversal, absolute paths, and Windows-style path escapes
        normalized = key.replace("\\", "/")
        normalized = re.sub(r"^[a-zA-Z]:", "", normalized)
        safe_parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
        candidate = (self.base_dir / Path(*safe_parts)).resolve()
        if not candidate.is_relative_to(self.base_dir.resolve()):
            raise ValueError("Invalid storage key")
        return candidate

    def save(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        canonical = self._path(key)
        path = filesystem_path(canonical)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".upload-", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as f:
                shutil.copyfileobj(data, f)
                f.flush()
                os.fsync(f.fileno())
            if key.endswith("_ocr.txt"):
                os.replace(temporary, path)
            else:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if path.read_bytes() != Path(temporary).read_bytes():
                        raise ValueError("Originalbytes dürfen nicht überschrieben werden") from None
        finally:
            Path(temporary).unlink(missing_ok=True)
        logger.info("File saved: %s", key)
        return str(canonical)

    def get(self, key: str) -> Optional[bytes]:
        path = filesystem_path(self._path(key))
        if not path.exists():
            return None
        return path.read_bytes()

    def delete(self, key: str) -> bool:
        path = filesystem_path(self._path(key))
        if path.exists():
            path.unlink()
            logger.info("File deleted: %s", key)
            return True
        return False

    def exists(self, key: str) -> bool:
        return filesystem_path(self._path(key)).exists()

    def get_url(self, key: str) -> str:
        return f"/uploads/{key}"


class S3Storage(FileStorage):
    """S3-compatible storage (AWS S3, MinIO).

    Explicit configuration:
      S3_ENDPOINT_URL=http://localhost:9000  (for MinIO)
      S3_ACCESS_KEY=...
      S3_SECRET_KEY=...
      S3_BUCKET=immomanager
    """

    def __init__(
        self,
        endpoint_url: str = "",
        access_key: str = "",
        secret_key: str = "",
        bucket: str = "immomanager",
        region: str = "eu-central-1",
        client=None,
        bindings_factory=None,
        legacy_local=None,
    ):
        self.bucket = bucket
        self.bindings_factory = bindings_factory
        self.legacy_local = legacy_local
        self.endpoint_hash = hashlib.sha256((endpoint_url.rstrip("/") + "|" + region).encode()).hexdigest()
        self._client = client
        if client is not None:
            return
        from .s3_protocol import S3Client
        self._client = S3Client(endpoint_url, access_key, secret_key, region)

    def binding(self, key):
        if self.bindings_factory is None:
            return None
        from ..db.access_models import StorageBindingORM
        try:
            with self.bindings_factory() as session:
                row = session.get(StorageBindingORM, validate_key(key))
                if row is None:
                    return None
                if row.bucket != self.bucket or row.endpoint_hash != self.endpoint_hash:
                    raise StorageUnavailable("Original ist an einen anderen Speicher gebunden")
                return {"sha256": row.sha256, "size_bytes": row.size_bytes, "deleted": row.deleted}
        except StorageUnavailable:
            raise
        except Exception:
            raise StorageUnavailable("Speicherzuordnung konnte nicht gelesen werden") from None

    def _remember(self, key, content):
        if self.bindings_factory is None:
            return
        from sqlalchemy.exc import IntegrityError

        from ..db.access_models import StorageBindingORM
        digest = hashlib.sha256(content).hexdigest()
        try:
            with self.bindings_factory() as session:
                row = session.get(StorageBindingORM, key)
                if row is not None:
                    if row.bucket != self.bucket or row.endpoint_hash != self.endpoint_hash:
                        raise StorageUnavailable("Original ist an einen anderen Speicher gebunden")
                    if row.sha256 != digest and not key.endswith("_ocr.txt"):
                        raise StorageUnavailable("Originalbindung darf nicht verändert werden")
                    if row.deleted:
                        raise StorageUnavailable("Gelöschter Dateischlüssel darf nicht erneut verwendet werden")
                    row.sha256, row.size_bytes = digest, len(content)
                else:
                    session.add(StorageBindingORM(storage_key=key, bucket=self.bucket,
                        endpoint_hash=self.endpoint_hash, sha256=digest, size_bytes=len(content), deleted=False))
                session.commit()
        except IntegrityError:
            if self.binding(key) != {"sha256": digest, "size_bytes": len(content), "deleted": False}:
                raise StorageUnavailable("Gleichzeitiger Konflikt bei der Speicherzuordnung") from None
        except StorageUnavailable:
            raise
        except Exception:
            raise StorageUnavailable("Speicherzuordnung wurde nicht bestätigt. Identischen Upload erneut versuchen.") from None

    def _call(self, operation: str, key: str, **kwargs):
        validate_key(key)
        if self._client is None:
            raise StorageUnavailable("S3 ist nicht verfügbar")
        try:
            return getattr(self._client, operation)(Bucket=self.bucket, Key=key, **kwargs)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if operation in ("get_object", "head_object") and code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise StorageUnavailable("S3-Zugriff fehlgeschlagen; bitte erneut versuchen") from None

    def save(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        validate_key(key)
        content = data.read()
        bound = self.binding(key)
        if bound and bound["deleted"]:
            raise StorageUnavailable("Gelöschter Dateischlüssel darf nicht erneut verwendet werden")
        if self.legacy_local is not None and bound is None and self.legacy_local.exists(key):
            self.legacy_local.save(key, __import__("io").BytesIO(content), content_type)
            return self.get_url(key)
        options = {} if key.endswith("_ocr.txt") else {"IfNoneMatch": "*"}
        try:
            self._call("put_object", key, Body=content, ContentType=content_type,
                       Metadata={"sha256": hashlib.sha256(content).hexdigest()}, **options)
        except StorageUnavailable:
            # A lost successful PUT response may be retried only with identical bytes.
            if self._remote_get(key) != content:
                raise
        self._remember(key, content)
        logger.info("S3 file saved: %s/%s", self.bucket, key)
        return self.get_url(key)

    def get(self, key: str) -> Optional[bytes]:
        bound = self.binding(key)
        if bound and bound["deleted"]:
            return None
        if self.legacy_local is not None and bound is None:
            return self.legacy_local.get(key)
        content = self._remote_get(key)
        if bound and content is not None and (hashlib.sha256(content).hexdigest() != bound["sha256"]
                                              or len(content) != bound["size_bytes"]):
            raise StorageUnavailable("Original stimmt nicht mit seiner Speicherbindung überein")
        return content

    def _remote_get(self, key: str) -> Optional[bytes]:
        response = self._call("get_object", key)
        if response is None:
            return None
        try:
            content = response["Body"].read()
            expected = response.get("Metadata", {}).get("sha256")
            if expected and hashlib.sha256(content).hexdigest() != expected:
                raise StorageUnavailable("Originalprüfsumme weicht ab")
            return content
        except Exception:
            raise StorageUnavailable("S3-Original konnte nicht vollständig gelesen werden") from None
        finally:
            response["Body"].close()

    def delete(self, key: str) -> bool:
        bound = self.binding(key)
        if self.legacy_local is not None and bound is None:
            return self.legacy_local.delete(key)
        self._call("delete_object", key)
        # Retain the binding as a tombstone: reusing a key must never select another object.
        if bound and self.bindings_factory is not None:
            from ..db.access_models import StorageBindingORM
            with self.bindings_factory() as session:
                row = session.get(StorageBindingORM, key)
                row.deleted = True
                session.commit()
        return True

    def exists(self, key: str) -> bool:
        bound = self.binding(key)
        if bound and bound["deleted"]:
            return False
        if self.legacy_local is not None and bound is None:
            return self.legacy_local.exists(key)
        return self._call("head_object", key) is not None

    def get_url(self, key: str) -> str:
        from urllib.parse import quote
        return f"/uploads/{quote(validate_key(key), safe='/')}"


# Default: local storage
_storage: FileStorage | None = None


def get_file_storage() -> FileStorage:
    """Get the configured file storage instance."""
    global _storage
    if _storage is None:
        from ..config import settings
        if settings.file_storage_backend == "s3":
            if not settings.s3_access_key or not settings.s3_secret_key or not settings.s3_bucket:
                raise StorageUnavailable("S3-Konfiguration unvollständig")
            from ..db.session import SessionLocal
            _storage = S3Storage(settings.s3_endpoint_url, settings.s3_access_key,
                                 settings.s3_secret_key, settings.s3_bucket, settings.s3_region,
                                 bindings_factory=SessionLocal, legacy_local=LocalStorage())
        else:
            _storage = LocalStorage()
    return _storage


def set_file_storage(storage: FileStorage) -> None:
    """Set the global file storage instance."""
    global _storage
    _storage = storage
