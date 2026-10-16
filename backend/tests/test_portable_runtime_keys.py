"""Secret keys in a passphrase-protected runtime are real archived restore keys.

The source process and its environment are never consulted to open a private
SQL evidence token after an archive is extracted in a fresh installation.
"""
import json

import pytest

from backend.services import secret_box
from backend.services.full_backup import ENV, BackupError, _archived_connection_keys
from backend.services.portable_runtime import RUNTIME


def test_archived_runtime_secret_keys_can_read_frozen_sql_ciphertext_without_env_or_old_keyfile():
    raw = secret_box.new_key_material()
    expected = secret_box.parse_env_keys(raw)
    token = secret_box.seal_with(expected, "nur-synthetisch\x00ä", "connection/test/config")
    from_archive = _archived_connection_keys({RUNTIME: json.dumps({"secret_keys": raw}).encode()})
    assert [key.id for key in from_archive] == [key.id for key in expected]
    assert secret_box.open_with(from_archive, token, "connection/test/config") == "nur-synthetisch\x00ä"
    with pytest.raises(secret_box.SecretKeyMissing):
        secret_box.open_with(_archived_connection_keys({}), token, "connection/test/config")


@pytest.mark.parametrize("raw", [
    b"invalid-not-json",
    b'{"secret_keys":1234}',
    b'["wrong runtime structure"]',
    b'{"secret_keys":"invalid base64!"}',
])
def test_corrupt_archived_runtime_key_format_fails_closed_without_leaking_raw_key_values(raw):
    with pytest.raises(BackupError, match="Archivierte Entschlüsselungsschlüssel") as error:
        _archived_connection_keys({RUNTIME: raw})
    assert "invalid-not-json" not in str(error.value)
    assert "invalid base64!" not in str(error.value)


def test_same_archived_key_from_runtime_and_env_is_unambiguous():
    raw = secret_box.new_key_material()
    keys = _archived_connection_keys({
        RUNTIME: json.dumps({"secret_keys": raw}).encode(),
        ENV: ("SECRET_KEYS=" + raw).encode(),
    })
    assert len(keys) == 1
    assert keys[0].id == secret_box.parse_env_keys(raw)[0].id
