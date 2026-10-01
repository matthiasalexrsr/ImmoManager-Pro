"""Authenticated Account.iban encryption, independent of session signing keys.

New ciphertexts are deterministic AES-SIV so the existing IBAN uniqueness
constraint remains meaningful. Legacy JWT-derived Fernet and plaintext values
are readable; converting an existing database is an explicit offline operation.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from sqlalchemy.exc import DontWrapMixin

_CONTEXT = b"immomanager/account.iban/aes-siv/v1"
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class IBANEncryptionError(Exception, DontWrapMixin):
    """Safe error: no key, plaintext, ciphertext or SQL parameters in its text."""

    def __init__(self, code: str):
        self.code = code
        self.recovery = "Vollständige Schlüsselkonfiguration aus der gesicherten Installation wiederherstellen; keine Kontodaten überschreiben."
        super().__init__(f"{code}: IBAN-Verschlüsselung ist nicht verfügbar. {self.recovery}")


def _dependencies():
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.fernet import Fernet, InvalidToken
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESSIV
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError:
        raise IBANEncryptionError("ENCRYPTION_DEPENDENCY_MISSING") from None
    return AESSIV, HKDF, hashes, Fernet, InvalidToken, InvalidTag


def _decode_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError, AttributeError):
        raise IBANEncryptionError("ENCRYPTION_KEY_INVALID") from None
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii") != value:
        raise IBANEncryptionError("ENCRYPTION_KEY_INVALID")
    return raw


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


@dataclass(frozen=True)
class IBANKeyring:
    active_key_id: str
    keys: Mapping[str, str] = field(repr=False)
    legacy_jwt_keys: tuple[str, ...] = field(default=(), repr=False)
    index_key: str | None = field(default=None, repr=False)

    def __post_init__(self):
        legacy_read = not self.keys and not self.active_key_id and self.legacy_jwt_keys
        if not legacy_read and (not _KEY_ID.fullmatch(self.active_key_id or "") or self.active_key_id not in self.keys):
            raise IBANEncryptionError("ENCRYPTION_ACTIVE_KEY_MISSING")
        if any(not isinstance(key, str) or not _KEY_ID.fullmatch(key) for key in self.keys):
            raise IBANEncryptionError("ENCRYPTION_KEY_ID_INVALID")
        for value in self.keys.values():
            _decode_key(value)
        if self.index_key:
            _decode_key(self.index_key)
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))
        object.__setattr__(self, "legacy_jwt_keys", tuple(dict.fromkeys(self.legacy_jwt_keys)))

    def fingerprint(self, value: str | None) -> str | None:
        plain = self.decrypt(value)
        canonical = re.sub(r"\s+", "", plain).upper() if plain else ""
        if not canonical:
            return None
        if not self.index_key:
            raise IBANEncryptionError("ENCRYPTION_INDEX_KEY_MISSING")
        return hmac.new(
            _decode_key(self.index_key),
            b"immomanager/account.iban/index/v1\0" + canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _cipher(self, key_id: str):
        if key_id not in self.keys:
            raise IBANEncryptionError("ENCRYPTION_KEY_UNAVAILABLE")
        aessiv, hkdf, hashes, *_ = _dependencies()
        raw = _decode_key(self.keys[key_id])
        try:
            key = hkdf(algorithm=hashes.SHA256(), length=64, salt=None, info=_CONTEXT).derive(raw)
            return aessiv(key)
        except Exception:
            raise IBANEncryptionError("ENCRYPTION_DEPENDENCY_UNAVAILABLE") from None

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return value
        # Administrative imports may contain an existing encrypted value. It
        # must authenticate before re-encryption; never double-encrypt a token.
        plain = self.decrypt(value)
        assert plain is not None
        if not self.active_key_id:
            raise IBANEncryptionError("ENCRYPTION_KEY_MISSING")
        header = f"enc:v1:{self.active_key_id}:"
        token = self._cipher(self.active_key_id).encrypt(plain.encode("utf-8"), [_CONTEXT, header.encode("ascii")])
        return header + base64.urlsafe_b64encode(token).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value or not value.startswith("enc:"):
            return value
        if value.startswith("enc:v"):
            parts = value.split(":", 3)
            if len(parts) != 4 or parts[1] != "v1" or not _KEY_ID.fullmatch(parts[2]):
                raise IBANEncryptionError("ENCRYPTION_CIPHERTEXT_VERSION_INVALID")
            _, _, key_id, encoded = parts
            try:
                token = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
                if base64.urlsafe_b64encode(token).decode("ascii") != encoded:
                    raise ValueError()
                return (
                    self._cipher(key_id).decrypt(token, [_CONTEXT, f"enc:v1:{key_id}:".encode("ascii")]).decode("utf-8")
                )
            except IBANEncryptionError:
                raise
            except Exception:
                raise IBANEncryptionError("ENCRYPTION_AUTHENTICATION_FAILED") from None
        *_, fernet, invalid_token, _ = _dependencies()
        for secret in self.legacy_jwt_keys:
            key = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"immomanager-iban-encryption-salt", 100_000)
            try:
                return fernet(base64.urlsafe_b64encode(key)).decrypt(value[4:].encode()).decode("utf-8")
            except (invalid_token, ValueError, UnicodeError):
                continue
        raise IBANEncryptionError("ENCRYPTION_LEGACY_KEY_UNAVAILABLE")


def keyring_from_configuration(values: Mapping) -> IBANKeyring:
    """Explicit configuration only. No ambient fallback during recovery."""
    normalized = {str(key).lower(): value for key, value in values.items()}
    single = normalized.get("encryption_key") or ""
    supplied = normalized.get("encryption_keyring") or ""
    active = normalized.get("encryption_active_key_id") or "default"
    legacy = normalized.get("encryption_legacy_jwt_keys") or "[]"
    jwt_secret = normalized.get("jwt_secret_key") or ""
    index_key = normalized.get("encryption_index_key") or None
    try:
        keys = json.loads(supplied) if isinstance(supplied, str) and supplied else supplied
        old = json.loads(legacy) if isinstance(legacy, str) else legacy
    except (ValueError, TypeError):
        raise IBANEncryptionError("ENCRYPTION_CONFIGURATION_INVALID") from None
    if single and supplied:
        raise IBANEncryptionError("ENCRYPTION_CONFIGURATION_AMBIGUOUS")
    if single:
        keys = {active: single}
    if not isinstance(old, list) or any(not isinstance(secret, str) or not secret for secret in old):
        raise IBANEncryptionError("ENCRYPTION_CONFIGURATION_INVALID")
    if not keys and (old or jwt_secret):
        return IBANKeyring("", {}, tuple(old) + ((jwt_secret,) if jwt_secret else ()), index_key)
    if not isinstance(keys, dict) or not keys:
        raise IBANEncryptionError("ENCRYPTION_KEY_MISSING")
    return IBANKeyring(active, keys, tuple(old) + ((jwt_secret,) if jwt_secret else ()), index_key)


@lru_cache(maxsize=8)
def _configured(single, supplied, active, legacy, jwt_secret, index_key):
    return keyring_from_configuration(
        dict(
            encryption_key=single,
            encryption_keyring=supplied,
            encryption_active_key_id=active,
            encryption_legacy_jwt_keys=legacy,
            jwt_secret_key=jwt_secret,
            encryption_index_key=index_key,
        )
    )


def current_keyring() -> IBANKeyring:
    # Resolve dynamically: ExplicitSettings during recovery must override a
    # terminal's inherited values, including deliberately empty fields.
    from ..config import settings

    names = (
        "encryption_key",
        "encryption_keyring",
        "encryption_active_key_id",
        "encryption_legacy_jwt_keys",
        "jwt_secret_key",
        "encryption_index_key",
    )
    values = tuple(getattr(settings, name, os.environ.get(name.upper(), "")) for name in names)
    return _configured(*values)


def encrypt_iban(iban: str | None) -> str | None:
    return current_keyring().encrypt(iban) if iban else iban


def decrypt_iban(stored: str | None) -> str | None:
    # Reading an old plaintext field must not pretend the database was migrated.
    return current_keyring().decrypt(stored) if stored and stored.startswith("enc:") else stored


def mask_iban(iban: str | None) -> str:
    plain = decrypt_iban(iban)
    return f"****{plain[-4:]}" if plain and len(plain) >= 4 else "****"


def verify_iban_database(database: Path, configuration: Mapping | IBANKeyring, *, deadline: float | None = None):
    """Read-only recovery proof for all IBAN columns, including legacy values."""
    ring = configuration if isinstance(configuration, IBANKeyring) else None
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        if deadline is not None:
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (name,) in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            if "iban" not in {row[1] for row in db.execute("PRAGMA table_xinfo(" + quoted + ")")}:
                continue
            for (value,) in db.execute("SELECT iban FROM " + quoted):
                if deadline is not None and time.monotonic() >= deadline:
                    raise IBANEncryptionError("ENCRYPTION_VERIFICATION_TIMEOUT")
                if isinstance(value, str) and value.startswith("enc:"):
                    if ring is None:
                        assert isinstance(configuration, Mapping)
                        ring = keyring_from_configuration(configuration)
                    ring.decrypt(value)
