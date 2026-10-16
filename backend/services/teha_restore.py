"""Read-only TEHA archive audit for an explicitly selected restore database.

Caller supplies the restored key box. This module never reads installation
configuration, invokes a provider, repairs data, or treats an unavailable key
as an empty archive. Full backup already includes all SQL tables and keyring.
"""
import hashlib
import json

from sqlalchemy import inspect, select

from ..db.document_version_models import DocumentVersionORM
from ..db.integration_connection_models import IntegrationActionRunORM
from ..db.teha_models import TehaBatchORM, TehaItemORM, TehaMappingORM, TehaReceiptORM, TehaReturnDraftORM
from . import secret_box
from .document_version_validation import verify_document_versions
from .teha_receive import identity


def needed_key_ids(connection, tables):
    """Enumerate every private TEHA source key from a single backup snapshot.

    Queries use hard-coded internal table/column names, not external inputs.
    The SQLAlchemy and sqlite3 branches inspect exactly the same source.
    """
    columns = (("teha_receive_items", "source_token"),
               ("teha_mappings", "target_token"),
               ("teha_publication_receipts", "evidence_token"),
               ("teha_return_drafts", "snapshot_token"))
    result = set()
    for table, column in columns:
        if table not in tables:
            continue
        query = f'SELECT "{column}" FROM "{table}"'
        rows = (connection.exec_driver_sql(query) if hasattr(connection, "exec_driver_sql")
                else connection.execute(query))
        for (token,) in rows:
            result.add(secret_box.token_key_id(token))
    return sorted(result)


def verify_teha_with_keys(connection, keys):
    """No runtime keyring, provider, session or mutable source is consulted."""
    class ArchiveOnlyBox:
        def open(self, token, context):
            return secret_box.open_with(keys, token, context)

    return verify_teha_restore(connection, ArchiveOnlyBox())


def verify_teha_restore(connection, box):
    models = (TehaBatchORM, TehaItemORM, TehaMappingORM, TehaReceiptORM, TehaReturnDraftORM)
    names = {model.__tablename__ for model in models}
    present = names & set(inspect(connection).get_table_names())
    if not present:
        return {"batches": 0, "items": 0, "mappings": 0, "receipts": 0, "returns": 0}
    if present != names:
        raise ValueError("Unvollständiges TEHA-Schema in der Wiederherstellung")
    def rows(model):
        return {row['id']: dict(row) for row in connection.execute(select(model.__table__)).mappings()}
    def open_value(token, context):
        return json.loads(box.open(token, context))
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    batches, items, mappings, receipts, returns = [rows(model) for model in models]
    runs = rows(IntegrationActionRunORM)
    versions = rows(DocumentVersionORM)
    for batch in batches.values():
        run = runs[batch['run_id']]
        if run['connection_id'] != batch['connection_id'] or run['result_sha256'] != batch['source_sha256']:
            raise ValueError("TEHA-Quelllauf und Checkpoint stimmen nicht überein")
        positions = sorted(item['position'] for item in items.values() if item['batch_id'] == batch['id'])
        if positions != list(range(batch['next_index'])) or (batch['state'] == 'ready' and batch['next_index'] != batch['total']):
            raise ValueError("TEHA-Empfang enthält fehlende oder doppelte Seiten")
    for item in items.values():
        source = open_value(item['source_token'], 'teha-item/' + item['id'])
        if digest(source) != item['source_sha256'] or identity(source) != item['identity_sha256'] or source.get('content_sha256') != item['content_sha256']:
            raise ValueError("TEHA-Rohquelle stimmt nicht mit ihrem Hash überein")
        if batches[item['batch_id']]['connection_id'] != item['connection_id']:
            raise ValueError("TEHA-Rohquelle gehört zu einer anderen Verbindung")
    for mapping in mappings.values():
        targets = open_value(mapping['target_token'], 'teha-mapping/' + mapping['id'])
        if not targets or len({t['kind'] for t in targets}) != len(targets):
            raise ValueError("Beschädigte TEHA-Zuordnung")
    for receipt in receipts.values():
        source = items[receipt['item_id']]
        evidence = open_value(receipt['evidence_token'], 'teha-receipt/' + receipt['id'])
        if any(source[key] != receipt[key] for key in ('connection_id', 'identity_sha256', 'source_sha256', 'content_sha256')):
            raise ValueError("TEHA-Receipt passt nicht zur Originalquelle")
        if digest(evidence['targets']) != receipt['mapping_sha256']:
            raise ValueError("TEHA-Receipt-Zuordnung stimmt nicht mit ihrem Hash überein")
        if receipt['predecessor_id']:
            previous = receipts[receipt['predecessor_id']]
            if previous['connection_id'] != receipt['connection_id'] or previous['identity_sha256'] != receipt['identity_sha256']:
                raise ValueError("TEHA-Vorgänger gehört zu einer anderen externen Identität")
        if receipt['document_id']:
            version = versions[receipt['version_id']]
            if version['document_id'] != receipt['document_id'] or version['sha256'] != receipt['content_sha256']:
                raise ValueError("TEHA-Originalversion und Receipt stimmen nicht überein")
    for draft in returns.values():
        snapshot = open_value(draft['snapshot_token'], 'teha-return/' + draft['id'])
        if digest(snapshot) != draft['snapshot_sha256'] or snapshot['external_write_enabled'] is not False or snapshot['portal_contract'] is not None:
            raise ValueError("TEHA-Rückübertragungsvorbereitung ist beschädigt oder behauptet einen unbelegten Schreibvertrag")
        if items[draft['item_id']]['connection_id'] != draft['connection_id']:
            raise ValueError("TEHA-Vorbereitung gehört zu einer anderen Verbindung")
    verify_document_versions(connection)
    return {"batches": len(batches), "items": len(items), "mappings": len(mappings), "receipts": len(receipts), "returns": len(returns)}
