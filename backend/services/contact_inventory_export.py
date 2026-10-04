"""Complete contact CSV through the shared, tested bounded snapshot exporter."""

from . import contact_inventory as inventory
from .inventory_export import csv_chunks as export_chunks

FIELDS = (*inventory.FIELDS, "display_name")


def csv_chunks(store, query, *, token=None, chunk_size=100):
    return export_chunks(store, query, inventory=inventory, fields=FIELDS, token=token, chunk_size=chunk_size)
