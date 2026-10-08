"""Authenticated encryption of configuration secrets at rest (AES-256-GCM, key ring with key ids).

Token format: ``enc:v1:<key id>:<base64url(nonce || ciphertext || tag)>``. The key id travels
with every ciphertext, so keys can be rotated: new values use the active key, old values stay
readable as long as their key is in the ring. The associated data binds a token to its field
(context), so a token copied into another field does not decrypt.

Keys come from SECRET_KEYS (comma-separated base64url 32-byte keys, first one active; never
written to disk by the program) or from the key file in the data directory, created with
owner-only permissions on the first secret that is stored. A missing key is an error, never
a silent reset: ciphertext without its key raises SecretKeyMissing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "enc:v1:"
KEYRING_FORMAT = "immomanager-keyring"
KEYRING_VERSION = 1
_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NONCE_BYTES = 12


class SecretError(RuntimeError):
    """A secret cannot be stored or read; nothing was changed."""


class SecretKeyMissing(SecretError):
    def __init__(self, key_id: str, key_file: Path | None = None):
        self.key_id = key_id
        where = f" (Schlüsseldatei {key_file})" if key_file else ""
        super().__init__(
            f"Verschlüsselte Geheimnisse benötigen den Schlüssel „{key_id}“, der nicht vorhanden ist{where}. "
            "Schlüsseldatei aus dem Vollbackup wiederherstellen oder SECRET_KEYS setzen; "
            "die Werte werden nicht zurückgesetzt."
        )


class SecretCorrupt(SecretError):
    pass


def is_sealed(value: object) -> bool:
    return isinstance(value, str) and value.startswith(TOKEN_PREFIX)


def token_key_id(token: str) -> str:
    if not is_sealed(token):
        raise SecretCorrupt("Kein verschlüsselter Wert")
    key_id, sep, _ = token[len(TOKEN_PREFIX):].partition(":")
    if not sep or not _KEY_ID.match(key_id):
        raise SecretCorrupt("Verschlüsselter Wert hat kein gültiges Format")
    return key_id


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise SecretCorrupt("Ungültige Base64-Kodierung") from exc


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _aad(key_id: str, context: str) -> bytes:
    return f"immomanager-secret-v1|{key_id}|{context}".encode()


def new_key_material() -> str:
    """A fresh key for SECRET_KEYS (base64url, 32 bytes)."""
    return _b64encode(secrets.token_bytes(32))


@dataclass(frozen=True)
class Key:
    id: str
    material: bytes
    source: str            # "env" or "file"
    created_at: str | None = None


def env_key_id(material: bytes) -> str:
    return "env-" + hashlib.sha256(material).hexdigest()[:12]


def parse_env_keys(value: str) -> list[Key]:
    keys = []
    for part in (item.strip() for item in (value or "").split(",")):
        if not part:
            continue
        material = _b64decode(part)
        if len(material) != 32:
            raise SecretError("SECRET_KEYS: jeder Schlüssel muss 32 Byte (base64url) lang sein")
        keys.append(Key(env_key_id(material), material, "env"))
    return keys


def write_private_file(path: Path, data: bytes) -> None:
    """Atomically replace path with owner-only permissions (0600; directory 0700 on POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            logger.warning("Could not restrict permissions of %s", path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def parse_keyring(raw: bytes) -> list[Key]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SecretCorrupt("Schlüsseldatei ist beschädigt") from exc
    if not isinstance(data, dict) or data.get("format") != KEYRING_FORMAT or not isinstance(data.get("keys"), list):
        raise SecretCorrupt("Schlüsseldatei hat ein unbekanntes Format")
    if int(data.get("version", 0)) > KEYRING_VERSION:
        raise SecretCorrupt("Schlüsseldatei stammt aus einer neueren Programmversion")
    keys = []
    for entry in data["keys"]:
        key_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(key_id, str) or not _KEY_ID.match(key_id):
            raise SecretCorrupt("Schlüsseldatei enthält eine ungültige Schlüssel-ID")
        material = _b64decode(str(entry.get("key", "")))
        if len(material) != 32:
            raise SecretCorrupt(f"Schlüssel „{key_id}“ hat eine falsche Länge")
        keys.append(Key(key_id, material, "file", entry.get("created_at")))
    active = data.get("active")
    # the active key first: the order is how SecretBox picks the key for new values
    keys.sort(key=lambda key: key.id != active)
    return keys


def _keyring_bytes(keys: list[Key], active: str) -> bytes:
    payload = {
        "format": KEYRING_FORMAT,
        "version": KEYRING_VERSION,
        "active": active,
        "keys": [{"id": key.id, "created_at": key.created_at, "key": _b64encode(key.material)} for key in keys],
        "note": "ImmoManager Pro: Schlüssel für verschlüsselte Konfigurationsgeheimnisse. Mit dem Vollbackup "
                "sichern, getrennt aufbewahren, nicht weitergeben.",
    }
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


class SecretBox:
    """Seal and open secrets with the key ring; the file is re-read when it changes."""

    def __init__(self, key_file: Path, env_keys: str = ""):
        self.key_file = Path(key_file)
        self._env_keys = parse_env_keys(env_keys)
        self._lock = threading.RLock()
        self._cache: tuple[tuple[int, int] | None, list[Key]] | None = None

    # --- key ring -------------------------------------------------------------------
    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            stat = self.key_file.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _file_keys(self) -> list[Key]:
        with self._lock:
            stamp = self._file_stamp()
            if self._cache is not None and self._cache[0] == stamp:
                return self._cache[1]
            keys: list[Key] = []
            if stamp is not None:
                keys = parse_keyring(self.key_file.read_bytes())
                if os.name != "nt" and self.key_file.stat().st_mode & 0o077:
                    logger.warning("Key file %s is readable by other users; restrict it to the owner (chmod 600)",
                                   self.key_file)
            self._cache = (stamp, keys)
            return keys

    def keys(self) -> list[Key]:
        """Active key first: SECRET_KEYS before the key file."""
        return [*self._env_keys, *self._file_keys()]

    @property
    def uses_env_keys(self) -> bool:
        return bool(self._env_keys)

    def active_key_id(self) -> str | None:
        keys = self.keys()
        return keys[0].id if keys else None

    def key_ids(self) -> list[str]:
        return [key.id for key in self.keys()]

    def _active_key(self) -> Key:
        with self._lock:
            keys = self.keys()
            if keys:
                return keys[0]
            key = Key(self._new_key_id(), secrets.token_bytes(32), "file",
                      datetime.now(timezone.utc).isoformat(timespec="seconds"))
            write_private_file(self.key_file, _keyring_bytes([key], key.id))
            self._cache = None
            logger.info("Created key file %s (key id %s)", self.key_file, key.id)
            return key

    @staticmethod
    def _new_key_id() -> str:
        return f"k{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(4)}"

    def rotate(self) -> str:
        """Add a new file key and make it active; existing keys stay for decryption."""
        if self._env_keys:
            raise SecretError("SECRET_KEYS ist gesetzt: neuen Schlüssel dort voranstellen, den alten dahinter lassen")
        with self._lock:
            keys = self._file_keys()
            key = Key(self._new_key_id(), secrets.token_bytes(32), "file",
                      datetime.now(timezone.utc).isoformat(timespec="seconds"))
            write_private_file(self.key_file, _keyring_bytes([key, *keys], key.id))
            self._cache = None
            return key.id

    def keyring_file_bytes(self) -> bytes | None:
        try:
            return self.key_file.read_bytes()
        except FileNotFoundError:
            return None

    # --- sealing --------------------------------------------------------------------
    def seal(self, plaintext: str, context: str) -> str:
        key = self._active_key()
        nonce = secrets.token_bytes(_NONCE_BYTES)
        sealed = AESGCM(key.material).encrypt(nonce, plaintext.encode("utf-8"), _aad(key.id, context))
        return f"{TOKEN_PREFIX}{key.id}:{_b64encode(nonce + sealed)}"

    def open(self, token: str, context: str) -> str:
        key_id = token_key_id(token)
        key = next((item for item in self.keys() if item.id == key_id), None)
        if key is None:
            raise SecretKeyMissing(key_id, None if self._env_keys else self.key_file)
        raw = _b64decode(token[len(TOKEN_PREFIX) + len(key_id) + 1:])
        if len(raw) <= _NONCE_BYTES:
            raise SecretCorrupt("Verschlüsselter Wert ist abgeschnitten")
        try:
            plaintext = AESGCM(key.material).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], _aad(key_id, context))
        except InvalidTag as exc:
            raise SecretCorrupt(f"Verschlüsselter Wert für „{context}“ ist verändert oder gehört zu einem "
                                "anderen Feld") from exc
        return plaintext.decode("utf-8")


def keys_from_bytes(raw: bytes) -> list[Key]:
    """Keys of a key file given as bytes (e.g. read from a backup)."""
    return parse_keyring(raw)


def open_with(keys: list[Key], token: str, context: str) -> str:
    """Decrypt with an explicit key list (restore probes; never touches the live key file)."""
    key_id = token_key_id(token)
    key = next((item for item in keys if item.id == key_id), None)
    if key is None:
        raise SecretKeyMissing(key_id)
    raw = _b64decode(token[len(TOKEN_PREFIX) + len(key_id) + 1:])
    try:
        return AESGCM(key.material).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], _aad(key_id, context)).decode()
    except InvalidTag as exc:
        raise SecretCorrupt(f"Verschlüsselter Wert für „{context}“ ist verändert") from exc


# --- passphrase envelopes (backup copies of the key file and .env) ----------------------

_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def seal_with_passphrase(data: bytes, passphrase: str) -> bytes:
    if not passphrase:
        raise SecretError("Leere Passphrase")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(_NONCE_BYTES)
    key = _derive(passphrase, salt, **_SCRYPT)
    ciphertext = AESGCM(key).encrypt(nonce, data, b"immomanager-backup-secrets-v1")
    envelope = {"format": "immomanager-secrets-envelope", "version": 1, "kdf": "scrypt", **_SCRYPT,
                "salt": _b64encode(salt), "nonce": _b64encode(nonce), "ciphertext": _b64encode(ciphertext)}
    return json.dumps(envelope, indent=2).encode("utf-8")


def open_with_passphrase(raw: bytes, passphrase: str) -> bytes:
    try:
        envelope = json.loads(raw.decode("utf-8"))
        n, r, p = int(envelope["n"]), int(envelope["r"]), int(envelope["p"])
        salt, nonce = _b64decode(envelope["salt"]), _b64decode(envelope["nonce"])
        ciphertext = _b64decode(envelope["ciphertext"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise SecretCorrupt("Geschützte Schlüsselsicherung ist beschädigt") from exc
    if envelope.get("format") != "immomanager-secrets-envelope" or envelope.get("kdf") != "scrypt":
        raise SecretCorrupt("Geschützte Schlüsselsicherung hat ein unbekanntes Format")
    try:
        return AESGCM(_derive(passphrase, salt, n, r, p)).decrypt(nonce, ciphertext, b"immomanager-backup-secrets-v1")
    except InvalidTag as exc:
        raise SecretError("Passphrase falsch oder Schlüsselsicherung verändert") from exc


_default_box: SecretBox | None = None
_default_lock = threading.Lock()


def default_key_file() -> Path:
    from ..config import settings
    from ..paths import get_data_dir

    configured = settings.secret_key_file.strip()
    return Path(configured).expanduser().resolve() if configured else get_data_dir() / "secrets" / "keyring.json"


def default_secret_box() -> SecretBox:
    global _default_box
    with _default_lock:
        if _default_box is None:
            from ..config import settings

            _default_box = SecretBox(default_key_file(), settings.secret_keys)
        return _default_box
