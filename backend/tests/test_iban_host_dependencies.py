"""The offline host crypto CLI does not need the application database runtime."""

import subprocess
import sys

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine

from backend.db.encrypted_types import EncryptedIBAN, SQLIBANEncryptionError
from backend.services import iban_encryption


def test_host_backup_key_validation_and_crypto_work_without_sqlalchemy():
    script = '''
import importlib.abc
import sys
class NoDatabaseRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "sqlalchemy" or fullname.startswith("sqlalchemy."):
            raise ModuleNotFoundError("database runtime deliberately absent", name="sqlalchemy")
sys.meta_path.insert(0, NoDatabaseRuntime())
from backend.services.iban_encryption import IBANKeyring, generate_key
from scripts.private_server_backup import _parse_env
key, index = generate_key(), generate_key()
env = ("APP_ORIGIN=https://example.test\\nAPP_HOST=example.test\\nAPP_HTTP_PORT=8080\\nPOSTGRES_USER=immo\\nPOSTGRES_DB=immomanager\\nPOSTGRES_PASSWORD=" + "a" * 64 + "\\nJWT_SECRET_KEY=" + "b" * 96 + "\\nENCRYPTION_KEY=" + key + "\\nENCRYPTION_INDEX_KEY=" + index + "\\n").encode()
assert _parse_env(env)["ENCRYPTION_KEY"] == key
ring = IBANKeyring("default", {"default": key}, (), index)
value = "DE" + "1" * 20
assert ring.decrypt(ring.encrypt(value)) == value
assert not any(name == "sqlalchemy" or name.startswith("sqlalchemy.") for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_sql_bind_failure_preserves_safe_error_without_statement_or_plaintext(monkeypatch):
    def unavailable():
        raise iban_encryption.IBANEncryptionError("ENCRYPTION_KEY_MISSING")
    monkeypatch.setattr(iban_encryption, "current_keyring", unavailable)
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    table = Table("synthetic", metadata, Column("iban", EncryptedIBAN()))
    value = "DE" + "9" * 20
    try:
        metadata.create_all(engine)
        with engine.begin() as connection, pytest.raises(SQLIBANEncryptionError) as error:
            connection.execute(table.insert().values(iban=value))
        assert isinstance(error.value, iban_encryption.IBANEncryptionError)
        assert value not in str(error.value)
        assert "INSERT" not in str(error.value)
        assert error.value.code == "ENCRYPTION_KEY_MISSING"
    finally:
        engine.dispose()
