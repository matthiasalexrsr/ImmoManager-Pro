"""Complete unit CSV through the shared, tested bounded snapshot exporter."""

from . import unit_inventory as inventory
from .inventory_export import csv_chunks as export_chunks

FIELDS = ("id", "label", "property_name", "unit_type", "status", "area_sqm", "rooms", "floor",
          "cold_rent", "service_charge_advance", "heating_advance", "person_count", "tenant_name",
          "active_contract_count", "has_contract", "property_id", "updated_at")


def csv_chunks(store, query, *, token=None, chunk_size=100):
    return export_chunks(store, query, inventory=inventory, fields=FIELDS, token=token, chunk_size=chunk_size)
