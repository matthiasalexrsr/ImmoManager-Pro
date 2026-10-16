"""Read-only fingerprints of an owned synthetic database, never a user installation.

The public JSON format intentionally refuses private bank/integration evidence.
This internal QA oracle covers those rows too without weakening that API guard.
Only counts and hashes leave this process; no payloads or secret bytes do.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path


def snapshot(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    marker = json.loads((directory / '.xstress-owned.json').read_text(encoding='utf-8'))
    if marker.get('kind') != 'synthetic-xstress' or Path(marker['parent']).resolve() != directory.parent:
        raise ValueError('Not an owned synthetic fixture')
    database = (directory / 'app.db').resolve(strict=True)
    if database.parent != directory:
        raise ValueError('Database escapes the fixture')
    # Run as a subprocess with this fixture's isolated environment. Importing the
    # schema here cannot bind config/logs/keys to either real installation.
    from backend.services.data_snapshot import entity_specs

    business = {spec.key for spec in entity_specs()} | {'receivable_settlements', 'saved_finance_reports'}
    prefixes = ('bank_', 'integration_', 'finance_', 'financial_', 'communication_',
                'teha_', 'channel_', 'document_')
    counts, digests = {}, {}
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if row[0] in business or row[0].startswith(prefixes)]
        for table in sorted(tables):
            quoted = '"' + table.replace('"', '""') + '"'
            rows = connection.execute('SELECT * FROM ' + quoted).fetchall()
            canon = sorted(json.dumps({key: value for key, value in dict(row).items() if key != 'updated_at'},
                                      sort_keys=True, default=lambda value: value.hex() if isinstance(value, bytes) else str(value))
                           for row in rows)
            counts[table] = len(rows)
            digests[table] = hashlib.sha256('\n'.join(canon).encode()).hexdigest()[:16]
    return {'counts': counts, 'digest': digests}


if __name__ == '__main__':
    print(json.dumps(snapshot(Path(sys.argv[1])), sort_keys=True))
