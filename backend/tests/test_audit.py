"""Tests for audit logging."""

import pytest

from backend.audit import InMemoryAuditStore, clear_audit_logs, list_audit_logs, log_action
from backend.models import AuditLogEntry


@pytest.fixture(autouse=True)
def _clean_audit():
    clear_audit_logs()
    yield
    clear_audit_logs()


class TestAuditLog:
    def test_memory_read_does_not_expose_or_follow_the_mutable_journal(self):
        journal = InMemoryAuditStore()
        first = AuditLogEntry(id="first", action="create", entity_type="property", entity_id="p-1")
        second = first.model_copy(update={"id": "second"})
        journal.add(first)
        snapshot = journal.list_all()
        journal.add(second)
        assert [entry.id for entry in snapshot] == ["first"]
        snapshot.clear()
        assert [entry.id for entry in journal.list_all()] == ["first", "second"]
        journal.clear()
        assert journal.list_all() == []

    def test_log_action(self):
        entry = log_action(
            action="create",
            entity_type="portfolio",
            entity_id="p-123",
            user_id="u-1",
            username="admin",
        )
        assert entry.action == "create"
        assert entry.entity_type == "portfolio"
        assert entry.entity_id == "p-123"
        assert entry.user_id == "u-1"

    def test_log_with_changes(self):
        entry = log_action(
            action="update",
            entity_type="property",
            entity_id="prop-1",
            changes={"name": {"old": "Haus A", "new": "Haus B"}},
        )
        assert entry.changes is not None
        assert "Haus A" in entry.changes

    def test_list_all(self):
        log_action(action="create", entity_type="portfolio", entity_id="p-1")
        log_action(action="delete", entity_type="unit", entity_id="u-1")
        assert len(list_audit_logs()) == 2

    def test_filter_by_entity_type(self):
        log_action(action="create", entity_type="portfolio", entity_id="p-1")
        log_action(action="create", entity_type="unit", entity_id="u-1")
        results = list_audit_logs(entity_type="portfolio")
        assert len(results) == 1
        assert results[0].entity_type == "portfolio"

    def test_filter_by_entity_id(self):
        log_action(action="create", entity_type="portfolio", entity_id="p-1")
        log_action(action="update", entity_type="portfolio", entity_id="p-1")
        log_action(action="create", entity_type="portfolio", entity_id="p-2")
        results = list_audit_logs(entity_id="p-1")
        assert len(results) == 2

    def test_filter_by_user_id(self):
        log_action(action="create", entity_type="portfolio", entity_id="p-1", user_id="u-1")
        log_action(action="create", entity_type="portfolio", entity_id="p-2", user_id="u-2")
        results = list_audit_logs(user_id="u-1")
        assert len(results) == 1

    def test_filter_by_action(self):
        log_action(action="create", entity_type="portfolio", entity_id="p-1")
        log_action(action="delete", entity_type="portfolio", entity_id="p-1")
        results = list_audit_logs(action="delete")
        assert len(results) == 1

    def test_clear(self):
        log_action(action="create", entity_type="portfolio", entity_id="p-1")
        clear_audit_logs()
        assert len(list_audit_logs()) == 0
