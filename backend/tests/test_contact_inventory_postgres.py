"""Strict disposable PostgreSQL evidence for contacts."""

from backend.tests.test_contact_inventory import (
    test_contact_export_concurrent_change as changed_export,
)
from backend.tests.test_contact_inventory import (
    test_explicit_contact_grants_and_export_revocation as grants,
)
from backend.tests.test_contact_inventory import (
    test_full_source_and_legacy_offset_without_materializing_all_contacts as full_source,
)
from backend.tests.test_contact_inventory import test_names_empty_fields_and_unicode_search as names
from backend.tests.test_contact_inventory import test_stable_cursor_nulls_and_binding as stable_cursor
from backend.tests.test_contract_lifecycle_postgres import postgres as postgres


def test_postgres_full_contacts_source(postgres, monkeypatch):
    full_source(postgres.store, monkeypatch)


def test_postgres_contact_scope_grants(postgres, monkeypatch):
    grants(postgres.store, monkeypatch)


def test_postgres_contact_null_names(postgres):
    names(postgres.store)


def test_postgres_contact_stable_cursor(postgres):
    stable_cursor(postgres.store, "city", "desc")


def test_postgres_contact_export_change(postgres):
    changed_export(postgres.store)
