"""Explicit actual PostgreSQL parity and complete export evidence."""

from backend.tests.test_contract_lifecycle_postgres import postgres as postgres
from backend.tests.test_document_inventory import (
    test_dates_nulls_ties_and_bound_cursor as stable_pages,
)
from backend.tests.test_document_inventory import (
    test_full_sources_beyond_ten_thousand_with_inherited_names_and_no_large_fields as full_source,
)
from backend.tests.test_inventory_export_consistency import (
    test_sql_concurrent_source_change_aborts_complete_export as changed_export,
)


def test_postgres_full_documents_source(postgres, monkeypatch):
    full_source(postgres.store, monkeypatch)


def test_postgres_document_dates_nulls_and_ties(postgres):
    stable_pages(postgres.store, "document_date", "desc")


def test_postgres_document_export_change_stops_stream(postgres):
    changed_export(postgres.store, "documents")
