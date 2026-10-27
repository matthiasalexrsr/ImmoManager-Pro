"""Bank ciphertext enumeration for full backup key coverage and offline verification."""
import base64
import hashlib
import json

from . import secret_box


def _rows(connection, sql):
    return connection.exec_driver_sql(sql) if hasattr(connection, 'exec_driver_sql') else connection.execute(sql)


def tokens(connection, tables):
    if 'bank_imports' in tables:
        for identifier, original, manifest in _rows(connection, 'SELECT id, original_token, manifest_token FROM bank_imports'):
            yield f'bank-original/{identifier}', original
            yield f'bank-manifest/{identifier}', manifest
    if 'bank_fints_sessions' in tables:
        for identifier, token in _rows(connection, 'SELECT id, private_token FROM bank_fints_sessions'):
            yield f'fints-session/{identifier}', token


def key_ids(connection, tables):
    return sorted({secret_box.token_key_id(token) for _, token in tokens(connection, tables)})


def verify(connection, tables, keys):
    count = 0
    if 'bank_imports' not in tables:
        return count
    for identifier, sha, original_token, manifest_token in _rows(connection,
            'SELECT id, source_sha256, original_token, manifest_token FROM bank_imports'):
        original = base64.b64decode(json.loads(secret_box.open_with(keys, original_token, f'bank-original/{identifier}')), validate=True)
        manifest = json.loads(secret_box.open_with(keys, manifest_token, f'bank-manifest/{identifier}'))
        preview_hash = hashlib.sha256(json.dumps(manifest['preview'], sort_keys=True, ensure_ascii=False,
                                                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if hashlib.sha256(original).hexdigest() != sha or preview_hash != manifest['preview_sha256']:
            raise ValueError('Bankoriginal oder Vorschau im Vollbackup stimmt nicht mit seinem Hash überein')
        count += 1
    return count
