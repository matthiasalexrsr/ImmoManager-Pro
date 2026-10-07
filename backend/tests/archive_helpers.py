"""Test helpers for archived document originals (immutable outside of tests)."""

from datetime import date

from backend.db.document_version_models import ARCHIVE_TABLES, install_guards
from backend.models import (
    ContractCreate,
    DocumentCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)


def purge_originals(store) -> None:
    """Remove every archived original: the guards are lifted for the moment of the delete."""
    if not hasattr(store, "db"):
        store.__dict__.pop("_document_originals", None)
        return
    store.db.rollback()
    with store.db.get_bind().connect() as connection:
        with connection.begin():
            drop_guards(connection)
            connection.exec_driver_sql(f"DELETE FROM {ARCHIVE_TABLES[1]}")
            connection.exec_driver_sql(f"DELETE FROM {ARCHIVE_TABLES[0]}")
            install_guards(connection)


def drop_guards(connection) -> None:
    for table in ARCHIVE_TABLES:
        if connection.dialect.name == "sqlite":
            for operation in ("update", "delete"):
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_{operation}")
        else:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_immutable ON {table}")


def lease_with_document(store, *, number="V-1", file_url="/uploads/documents/vertrag.pdf") -> dict:
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential", address_line="Bautzner Straße 61",
                                                postal_code="01099", city="Dresden"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential"))
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster"))
    contract = store.create_contract(ContractCreate(contract_number=number, property_id=prop.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date=date(2024, 1, 1)))
    document = store.create_document(DocumentCreate(property_id=prop.id, unit_id=unit.id, contract_id=contract.id,
                                                    title="Mietvertrag", document_type="mietvertrag",
                                                    file_url=file_url))
    return {"portfolio": portfolio, "property": prop, "unit": unit, "tenant": tenant, "contract": contract,
            "document": document}


def pdf_bytes(size: int) -> bytes:
    """A PDF-looking payload of `size` bytes with varied content."""
    body = bytes((index * 7 + index // 251) % 256 for index in range(max(size - 5, 0)))
    return (b"%PDF-" + body)[:size]
