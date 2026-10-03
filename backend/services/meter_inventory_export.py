"""Complete scoped meter CSV using the existing fenced snapshot exporter."""

from . import meter_inventory as inventory
from .inventory_export import csv_chunks as export_chunks

FIELDS = ("id", "serial_number", "property_id", "property_name", "unit_id", "unit_label", "meter_type",
          "measurement_unit", "is_active", "location", "supplier", "contract_number", "contract_end_date",
          "installation_date", "next_inspection", "last_reading_id", "last_reading_date", "last_reading_value", "updated_at")


def csv_chunks(store, query, *, token=None, chunk_size=100):
    return export_chunks(store, query, inventory=inventory, fields=FIELDS, token=token, chunk_size=chunk_size)
