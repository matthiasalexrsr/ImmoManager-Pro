"""Installation backup checks for encrypted communication originals, without account actions."""
import base64
import hashlib
import json

from . import secret_box


def query(connection, sql, parameters=()):
    if hasattr(connection, 'exec_driver_sql'):
        return connection.exec_driver_sql(sql, parameters, execution_options={'stream_results': True, 'max_row_buffer': 50})
    return connection.execute(sql, parameters)


def restored_keys(files, keyring_path, env_path, fallback=''):
    keys = secret_box.keys_from_bytes(files[keyring_path]) if keyring_path in files else []
    for line in files.get(env_path, b'').decode('utf-8', 'replace').splitlines():
        name, _, value = line.strip().partition('=')
        if name.strip() == 'SECRET_KEYS':
            keys += secret_box.parse_env_keys(value.strip().strip('"').strip("'"))
    return keys or (secret_box.parse_env_keys(fallback) if fallback else [])


def needed_key_ids(connection, tables):
    identifiers = set()
    for table, column in (('communication_items', 'payload_token'), ('communication_blocks', 'data_token')):
        if table not in tables:
            continue
        # Only the short envelope prefix is read; ciphertext never enters the backup manifest.
        for (prefix,) in query(connection, f'SELECT DISTINCT substr({column}, 1, 80) FROM {table}'):
            identifiers.add(secret_box.token_key_id(prefix))
    return sorted(identifiers)


def verify(connection, keys, tables):
    if 'communication_items' not in tables:
        return dict(items=0, originals=0, blocks=0)
    result = dict(items=0, originals=0, blocks=0)
    for identifier, token in query(connection, 'SELECT id, payload_token FROM communication_items'):
        json.loads(secret_box.open_with(keys, token, 'communication/' + identifier))
        result['items'] += 1
    for identifier, expected_hash, expected_size in query(connection, 'SELECT id, sha256, byte_length FROM communication_evidence'):
        digest = hashlib.sha256()
        length, sequence = 0, 0
        placeholder = '%s' if getattr(getattr(connection, 'dialect', None), 'name', '') == 'postgresql' else '?'
        sql = 'SELECT id, sequence, data_token FROM communication_blocks WHERE evidence_id=' + placeholder + ' ORDER BY sequence'
        for block_id, index, token in query(connection, sql, (identifier,)):
            if index != sequence:
                raise ValueError('Communication original has missing blocks')
            raw = base64.b64decode(json.loads(secret_box.open_with(keys, token, 'communication-block/' + block_id)), validate=True)
            digest.update(raw)
            length += len(raw)
            sequence += 1
        if length != expected_size or digest.hexdigest() != expected_hash:
            raise ValueError('Communication original integrity check failed')
        result['originals'] += 1
        result['blocks'] += sequence
    return result
