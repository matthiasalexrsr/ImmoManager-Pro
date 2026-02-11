"""IBAN encryption service for sensitive field storage.

Uses Fernet symmetric encryption (AES-128-CBC via cryptography library).
The encryption key is derived from JWT_SECRET_KEY using PBKDF2.
"""

import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Derive encryption key from JWT secret
_fernet = None


def _get_fernet():
    """Lazily initialize Fernet cipher from settings."""
    global _fernet
    if _fernet is not None:
        return _fernet

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography package not available. IBAN encryption disabled.")
        return None

    from ..config import settings
    # Derive a 32-byte key from the JWT secret using PBKDF2
    key_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        settings.jwt_secret_key.encode(),
        b"immomanager-iban-encryption-salt",
        100_000,
    )
    fernet_key = base64.urlsafe_b64encode(key_bytes[:32])
    _fernet = Fernet(fernet_key)
    return _fernet


def encrypt_iban(iban: str) -> str:
    """Encrypt an IBAN for secure storage.

    Returns the encrypted string prefixed with 'enc:'.
    If encryption is unavailable, returns the original IBAN.
    """
    if not iban:
        return iban

    f = _get_fernet()
    if f is None:
        return iban

    encrypted = f.encrypt(iban.encode()).decode()
    return f"enc:{encrypted}"


def decrypt_iban(stored: str) -> str:
    """Decrypt a stored IBAN.

    If the value doesn't start with 'enc:', returns it as-is (plain text).
    """
    if not stored or not stored.startswith("enc:"):
        return stored

    f = _get_fernet()
    if f is None:
        # Can't decrypt, return masked
        return "****"

    try:
        encrypted = stored[4:]  # Remove 'enc:' prefix
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        logger.warning("IBAN decryption failed")
        return "****"


def mask_iban(iban: str) -> str:
    """Mask an IBAN for display (show only last 4 characters).

    Example: DE89370400440532013000 -> ****3000
    """
    if not iban or len(iban) < 4:
        return "****"
    # First decrypt if encrypted
    plain = decrypt_iban(iban) if iban.startswith("enc:") else iban
    return f"****{plain[-4:]}"
