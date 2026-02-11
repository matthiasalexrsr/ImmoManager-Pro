"""File storage service abstraction.

Supports:
- LocalStorage (default): Files stored on local filesystem
- S3Storage: S3-compatible storage (AWS S3, MinIO)

Configure via FILE_STORAGE_BACKEND and S3_* environment variables.
"""

import logging
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional

logger = logging.getLogger(__name__)


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

    def __init__(self, base_dir: str = "uploads"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent path traversal
        safe_key = key.replace("..", "").lstrip("/")
        return self.base_dir / safe_key

    def save(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            shutil.copyfileobj(data, f)
        logger.info("File saved: %s", key)
        return str(path)

    def get(self, key: str) -> Optional[bytes]:
        path = self._path(key)
        if not path.exists():
            return None
        return path.read_bytes()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path.exists():
            path.unlink()
            logger.info("File deleted: %s", key)
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def get_url(self, key: str) -> str:
        return f"/uploads/{key}"


class S3Storage(FileStorage):
    """S3-compatible storage (AWS S3, MinIO).

    Requires:
      pip install boto3
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
    ):
        self.bucket = bucket
        self._client = None
        try:
            import boto3
            kwargs = {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "region_name": region,
            }
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            self._client = boto3.client("s3", **kwargs)
            logger.info("S3 storage connected: bucket=%s", bucket)
        except ImportError:
            logger.warning("boto3 not installed. S3 storage unavailable.")

    def save(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        if self._client is None:
            raise RuntimeError("S3 client not available. Install boto3.")
        self._client.upload_fileobj(data, self.bucket, key, ExtraArgs={"ContentType": content_type})
        logger.info("S3 file saved: %s/%s", self.bucket, key)
        return self.get_url(key)

    def get(self, key: str) -> Optional[bytes]:
        if self._client is None:
            return None
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except Exception:
            return None

    def delete(self, key: str) -> bool:
        if self._client is None:
            return False
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
            logger.info("S3 file deleted: %s/%s", self.bucket, key)
            return True
        except Exception:
            return False

    def exists(self, key: str) -> bool:
        if self._client is None:
            return False
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def get_url(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"


# Default: local storage
_storage: FileStorage = LocalStorage()


def get_file_storage() -> FileStorage:
    """Get the configured file storage instance."""
    return _storage


def set_file_storage(storage: FileStorage) -> None:
    """Set the global file storage instance."""
    global _storage
    _storage = storage
