"""Prepared pure candidate tests; no write or release authority is represented."""

import pytest

from backend.services.notification_inbox_read_support import notification_read_subject_hint

ALIASES = {"portfolio": "portfolios", "property": "properties", "unit": "units",
           "task": "tasks", "contract": "contracts", "thread": "message_threads"}


@pytest.mark.parametrize("unrestricted,kind,identifier,expected", [
    (True, "unit", "unit-one", True),
    (True, "task", "missing-task", True),
    (True, "tenant", "missing-tenant", True),
    (True, "unknown", "missing", True),
    (True, None, "broken-pair", True),
    (True, "unknown", None, True),
    (True, None, None, True),
    (False, "portfolio", "p-one", True),
    (False, "property", "property-one", True),
    (False, "unit", "unit-one", True),
    (False, None, None, True),  # Candidate still needs an actual Resourcegrant.
    (False, None, "broken-pair", False),
    (False, "unit", None, False),
    (False, "unit", " ", False),
    (False, "unit", 7, False),
    (False, "unknown", "id", False),
    (False, "task", "task-one", False),
    (False, "contract", "contract-one", False),
    (False, "thread", "thread-one", False),
    (False, "units", "unit-one", False),  # No inferred plural alias.
])
def test_subject_shape_is_only_a_supported_candidate(unrestricted, kind, identifier, expected):
    assert notification_read_subject_hint(status="unread", unrestricted=unrestricted,
        entity_type=kind, entity_id=identifier, resource_aliases=ALIASES) is expected


@pytest.mark.parametrize("status,unrestricted", [
    ("archived", True), ("deleted", True), ("", True), ("unread", 1), ("read", "all"),
])
def test_inactive_or_untyped_scope_hint_is_closed(status, unrestricted):
    assert notification_read_subject_hint(status=status, unrestricted=unrestricted,
        entity_type="unit", entity_id="unit-one", resource_aliases=ALIASES) is False


def test_central_mapping_is_supplied_and_no_alias_is_invented():
    assert notification_read_subject_hint(status="read", unrestricted=False,
        entity_type="unit", entity_id="unit-one", resource_aliases={}) is False
    assert notification_read_subject_hint(status="read", unrestricted=False,
        entity_type="new-central-alias", entity_id="unit-one",
        resource_aliases={"new-central-alias": "units"}) is True
