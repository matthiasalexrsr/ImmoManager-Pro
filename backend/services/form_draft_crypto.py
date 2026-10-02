"""Authenticated draft encryption, separated from IBAN and JWT field contexts."""

import base64

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .iban_encryption import _decode_key, current_keyring

CONTEXT = b"immomanager/private-form-draft/aes-gcm/v1"


class DraftCryptoError(ValueError):
    """No plaintext, SQL arguments or secret material in diagnostic messages."""


def _cipher(key_id, ring=None):
    ring = ring or current_keyring()
    if key_id not in ring.keys:
        raise DraftCryptoError("DRAFT_ENCRYPTION_KEY_UNAVAILABLE")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=CONTEXT).derive(_decode_key(ring.keys[key_id]))
    return AESGCM(key)


def encrypt(value: bytes, identity: bytes) -> str:
    import os
    key_id = current_keyring().active_key_id
    if not key_id:
        raise DraftCryptoError("DRAFT_ENCRYPTION_KEY_MISSING")
    header = "draft:v1:" + key_id + ":"
    nonce = os.urandom(12)
    data = nonce + _cipher(key_id).encrypt(nonce, value, CONTEXT + header.encode("ascii") + identity)
    return header + base64.urlsafe_b64encode(data).decode("ascii")


def decrypt(value: str, identity: bytes, ring=None) -> bytes:
    try:
        kind, version, key_id, encoded = value.split(":", 3)
        if kind != "draft" or version != "v1":
            raise ValueError()
        data = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(data) < 28 or base64.urlsafe_b64encode(data).decode("ascii") != encoded:
            raise ValueError()
        return _cipher(key_id, ring).decrypt(data[:12], data[12:], CONTEXT + f"draft:v1:{key_id}:".encode("ascii") + identity)
    except DraftCryptoError:
        raise
    except (InvalidTag, ValueError, UnicodeError):
        raise DraftCryptoError("DRAFT_ENCRYPTION_AUTHENTICATION_FAILED") from None


def verify_database(database, configuration, *, deadline=None):
    """Offline SQLite recovery validation with the archive's explicit keys.

    All ciphertexts are streamed; no current runtime/configuration fallback.
    Old installations without drafts remain compatible.
    """
    import json
    import sqlite3
    import time
    from contextlib import closing

    from .iban_encryption import IBANKeyring, keyring_from_configuration
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        if deadline is not None:
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='form_drafts'").fetchone()
        if not exists:
            return 0
        count = 0
        ring = configuration if isinstance(configuration, IBANKeyring) else keyring_from_configuration(configuration)
        budget = ciphertext_budget(configuration)
        for identifier, payload in connection.execute(
                "SELECT id, CASE WHEN length(payload) <= ? THEN payload ELSE NULL END FROM form_drafts", (budget,)):
            if deadline is not None and time.monotonic() > deadline:
                raise DraftCryptoError("DRAFT_VERIFICATION_TIMEOUT")
            try:
                if not isinstance(payload, str):
                    raise ValueError()
                value = json.loads(decrypt(payload, identifier.encode("ascii"), ring))
                if not isinstance(value, dict) or not isinstance(value.get("values"), dict):
                    raise ValueError()
            except (ValueError, UnicodeError, TypeError, AttributeError):
                raise DraftCryptoError("DRAFT_ENCRYPTION_AUTHENTICATION_FAILED") from None
            count += 1
        return count


def ciphertext_budget(configuration):
    """Bound one encrypted envelope using only the selected installation values."""
    try:
        raw = configuration.get("FORM_DRAFT_MAX_BYTES", configuration.get("form_draft_max_bytes", 262144)) if hasattr(configuration, "get") else 262144
        maximum = int(raw)
        if not 1024 <= maximum <= 16777216:
            raise ValueError()
    except (ValueError, TypeError):
        raise DraftCryptoError("DRAFT_CONFIGURATION_INVALID") from None
    # AES-GCM nonce/tag plus canonical base64 and the bounded version/key header.
    return 128 + 4 * ((maximum + 28 + 2) // 3)
