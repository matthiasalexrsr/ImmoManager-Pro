"""Equal clock ticks have a deterministic ID order across both history endpoints."""

from types import SimpleNamespace

from backend.models import ChangeHistoryEntry
from backend.routers import history


def test_equal_timestamps_have_stable_pages_and_entity_order(monkeypatch):
    rows = [ChangeHistoryEntry.model_validate({"id": id_, "entity_type": "tenant", "entity_id": "t1",
                                               "field_name": "name", "changed_at": "2026-10-07T12:00:00Z"})
            for id_ in ("a", "c", "b")]
    monkeypatch.setattr(history, "store", SimpleNamespace(
        list_change_history=lambda: list(rows), get_entity_history=lambda *args: list(rows)))
    pages = [history._page(None, None, i, 1)[0].id for i in range(3)]
    assert pages == ["c", "b", "a"]
    rows.reverse()
    assert [history._page(None, None, i, 1)[0].id for i in range(3)] == pages
    assert [row.id for row in history.get_entity_history("tenant", "t1")] == ["c", "b", "a"]
