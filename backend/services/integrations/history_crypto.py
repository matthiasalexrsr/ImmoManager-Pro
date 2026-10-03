"""Own AEAD domain, backed by stable field keys, never a JWT signer."""

import base64
import hashlib
import json
import os
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..iban_encryption import IBANEncryptionError, _decode_key, current_keyring, keyring_from_configuration
from .history_types import HistoryError

DOMAIN = b"immomanager/private-integration-history/aes-gcm/v1"
CHUNK_BYTES = 64 * 1024


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise HistoryError("HISTORY_CORRUPT") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def stamp(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError()
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat(timespec="microseconds")
    except (ValueError, OverflowError):
        raise HistoryError("HISTORY_CORRUPT") from None


def ring_for(configuration=None):
    try:
        return current_keyring() if configuration is None else configuration if hasattr(configuration, "keys") and hasattr(configuration, "active_key_id") else keyring_from_configuration(configuration)
    except IBANEncryptionError:
        raise HistoryError("HISTORY_KEY_UNAVAILABLE") from None


def _cipher(ring, identifier):
    if identifier not in ring.keys:
        raise HistoryError("HISTORY_KEY_UNAVAILABLE")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=DOMAIN).derive(_decode_key(ring.keys[identifier]))
    return AESGCM(key)


def encrypt(raw, identity, ring):
    if not ring.active_key_id:
        raise HistoryError("HISTORY_KEY_UNAVAILABLE")
    header = "history:v1:" + ring.active_key_id + ":"
    nonce = os.urandom(12)
    encoded = nonce + _cipher(ring, ring.active_key_id).encrypt(nonce, raw, DOMAIN + header.encode("ascii") + canonical(identity))
    return header + base64.urlsafe_b64encode(encoded).decode("ascii")


def decrypt(value, identity, ring):
    try:
        prefix, version, key_id, encoded = value.split(":", 3)
        if prefix != "history" or version != "v1":
            raise ValueError()
        raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(raw) < 28 or base64.urlsafe_b64encode(raw).decode("ascii") != encoded:
            raise ValueError()
        return _cipher(ring, key_id).decrypt(raw[:12], raw[12:], DOMAIN + f"history:v1:{key_id}:".encode("ascii") + canonical(identity))
    except HistoryError:
        raise
    except (InvalidTag, ValueError, UnicodeError, AttributeError, TypeError):
        raise HistoryError("HISTORY_CORRUPT") from None


def run_identity(row):
    return {key: stamp(row[key]) if key == "created_at" else row[key] for key in ("id", "integration_id", "run_sequence", "actor_id", "origin", "scope_kind", "created_at")}


def event_identity(run, row):
    success = row["success"]
    if success is not None and (type(success) not in (bool, int) or success not in (0, 1)):
        raise HistoryError("HISTORY_CORRUPT")
    return {"run": run_identity(run), "success": None if success is None else bool(success), **{key: stamp(row[key]) if key == "created_at" else row[key] for key in ("id", "run_id", "integration_id", "event_number", "journal_sequence", "state", "created_at", "previous_hash", "manifest")}}
