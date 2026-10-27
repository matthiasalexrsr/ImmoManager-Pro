"""Validate retained tax evidence in an isolated restored SQL database.

The caller supplies keys from that backup. This module never reads installation
configuration, authenticates a user or changes the restored database.
"""
import base64
import hashlib
import hmac
import json
import tempfile
from decimal import Decimal
from types import SimpleNamespace
from zipfile import ZipFile

from sqlalchemy import inspect, select

from ..db.datev_models import DatevBlockORM, DatevExportORM, DatevProfileORM
from ..db.tax_models import AnnualTaxProfileORM, AnnualTaxProjectionORM, AnnualTaxSourceORM
from .annual_tax_storage import read_profile, read_projection, verified_json
from .datev_export import read_export
from .datev_export import read_profile as read_datev_profile
from .secret_box import token_key_id


def rows(connection, model, *conditions, order=None):
    query = select(model.__table__).where(*conditions)
    if order is not None:
        query = query.order_by(order)
    # Connection.execution_options mutates the SQLAlchemy 2 connection. Keep
    # the server-side cursor local to this SELECT: restore later writes the
    # portal revocations and must not turn UPDATE into DECLARE ... CURSOR.
    for row in connection.execute(query.execution_options(stream_results=True)).mappings():
        yield SimpleNamespace(**row)


def needed_key_ids(connection):
    existing = set(inspect(connection).get_table_names())
    result = set()
    for model, column in ((AnnualTaxSourceORM, "source_json"), (DatevBlockORM, "token")):
        if model.__tablename__ in existing:
            for row in rows(connection, model):
                result.add(token_key_id(getattr(row, column)))
    return result


def verify_tax_archive(connection, opener):
    existing = set(inspect(connection).get_table_names())
    count = 0
    for model, reader in ((AnnualTaxProfileORM, read_profile), (DatevProfileORM, read_datev_profile)):
        if model.__tablename__ in existing:
            for row in rows(connection, model):
                profile = reader(row)
                if profile["spec"]["portfolio_id"] != row.portfolio_id:
                    raise ValueError("tax_profile_binding")
    if AnnualTaxProjectionORM.__tablename__ in existing:
        for projection in rows(connection, AnnualTaxProjectionORM):
            manifest = read_projection(projection)
            digest, sequence = hashlib.sha256(), 0
            totals = dict(cash_cents=0, income_cents=0, expense_cents=0, excluded_cash_cents=0, unclassified_cash_cents=0)
            for source in rows(connection, AnnualTaxSourceORM, AnnualTaxSourceORM.projection_id == projection.id,
                               order=AnnualTaxSourceORM.sequence_number):
                sequence += 1
                if source.sequence_number != sequence or source.portfolio_id != projection.portfolio_id:
                    raise ValueError("tax_source_sequence_or_scope")
                encoded = opener(source.source_json, f"annual-tax:{projection.id}:{sequence}")
                record = verified_json(encoded, source.sha256, "evidence")
                if source.booking_id != record["booking"]["id"]:
                    raise ValueError("tax_source_booking_binding")
                digest.update(encoded.encode("ascii") + b"\n")
                if record["classification_state"] == "included":
                    totals["cash_cents"] += int(record["booking"]["amount_cents"])
                for part in record["parts"]:
                    value = int(part["amount_cents"])
                    kind = part["treatment"]
                    target = "excluded_cash_cents" if kind == "excluded" else kind + "_cents"
                    totals[target] += -value if kind == "expense" else value
            if (sequence != manifest["source_rows"] or digest.hexdigest() != manifest["source_sha256"]
                    or totals != {k: int(v) for k, v in manifest["totals"].items()}):
                raise ValueError("tax_source_totals_or_hash")
            count += 1
    if DatevExportORM.__tablename__ in existing:
        for export in rows(connection, DatevExportORM):
            manifest = read_export(export)
            digest, sequence, size = hashlib.sha256(), 0, 0
            with tempfile.TemporaryFile() as archive_bytes:
                for block in rows(connection, DatevBlockORM, DatevBlockORM.export_id == export.id,
                                  order=DatevBlockORM.sequence_number):
                    sequence += 1
                    if block.sequence_number != sequence or block.portfolio_id != export.portfolio_id:
                        raise ValueError("datev_block_sequence_or_scope")
                    chunk = base64.b64decode(opener(block.token, f"datev:{export.id}:{sequence}"), validate=True)
                    digest.update(chunk)
                    size += len(chunk)
                    archive_bytes.write(chunk)
                if size != manifest["size"] or not hmac.compare_digest(digest.hexdigest(), manifest["sha256"]):
                    raise ValueError("datev_original_hash")
                archive_bytes.seek(0)
                with ZipFile(archive_bytes) as archive:
                    if archive.testzip() is not None:
                        raise ValueError("datev_original_zip")
                    source_digest, source_count = hashlib.sha256(), 0
                    income, expense = 0, 0
                    with archive.open("sources.jsonl") as sources:
                        for line in sources:
                            source_count += 1
                            source_digest.update(line)
                            value = int(Decimal(json.loads(line)["amount"]) * 100)
                            income += max(0, value)
                            expense += max(0, -value)
                    if (source_digest.hexdigest() != manifest["source_sha256"] or source_count != manifest["rows"]
                            or income != int(Decimal(manifest["income"]) * 100)
                            or expense != int(Decimal(manifest["expense"]) * 100)):
                        raise ValueError("datev_source_totals")
            count += 1
    return count
