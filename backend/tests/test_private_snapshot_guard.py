"""A partial JSON restore must never detach private provider evidence."""

import pytest

from backend.services.data_snapshot import (
    SNAPSHOT_FORMAT,
    SNAPSHOT_FORMAT_VERSION,
    SnapshotError,
    export_snapshot,
    import_snapshot,
)
from backend.storage import InMemoryStore


@pytest.mark.parametrize('family', ['integration_connections', 'channel_cases', 'channel_webhooks',
                                    'teha_receive_batches', 'communication_items'])
def test_partial_export_and_replace_refuse_private_records_before_any_data_changes(family):
    store = InMemoryStore()
    evidence = {'retained': object()}
    store.__dict__['_integration_connections'] = {family: evidence}
    empty = {'format': SNAPSHOT_FORMAT, 'format_version': SNAPSHOT_FORMAT_VERSION}
    with pytest.raises(SnapshotError, match='vollständige Sicherung'):
        export_snapshot(store)
    with pytest.raises(SnapshotError, match='vollständige Sicherung'):
        import_snapshot(store, empty, replace=True)
    assert store.__dict__['_integration_connections'][family] is evidence
    assert list(evidence) == ['retained']
