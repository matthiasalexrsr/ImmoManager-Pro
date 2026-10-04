"""Property CSV adapter: shared bounded export, exact public money and keys."""

from . import property_inventory as inventory
from .inventory_export import csv_chunks as shared_chunks
from .property_inventory_types import COUNT_FIELDS

FIELDS = (
    *inventory.PROPERTY_FIELDS, "portfolio_name", "address", "rent_currency", "unit_cold_rent_sum",
    *COUNT_FIELDS, "edit_etag",
)


def csv_chunks(store, query, *, token=None, chunk_size=100):
    # Root's additive prepare_read/page_position/export_row hooks are required.
    # They preserve the actual raw source position and fresh DTO comparison.
    inventory._scope(query, summary=True)
    engine = inventory._engine(store) if hasattr(store, "db") else None
    return shared_chunks(store, query, inventory=inventory, fields=FIELDS, token=token, chunk_size=chunk_size,
                         read_engine=engine)
