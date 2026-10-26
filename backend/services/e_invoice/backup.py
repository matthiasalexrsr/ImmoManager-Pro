"""Offline verification of receipt evidence before publishing a restored store."""
import hashlib

from sqlalchemy import inspect, select

from ...db.e_invoice_models import EInvoiceIntakeORM as Intake
from ...db.e_invoice_models import EInvoiceValidationORM as Validation
from ...db.orm_models import InvoiceORM
from .parser import MAX_FILE, MAX_XML, read


def verify(connection) -> dict:
    tables = set(inspect(connection).get_table_names())
    names = {Intake.__tablename__, Validation.__tablename__}
    if not names & tables:
        return {"intakes": 0, "validations": 0}
    if not names <= tables:
        raise ValueError("Partial receipt evidence")
    intakes = list(connection.execute(select(Intake.__table__)).mappings())
    runs = list(connection.execute(select(Validation.__table__)).mappings())
    invoices = {row["id"]: row for row in connection.execute(select(InvoiceORM.__table__)).mappings()}
    return verify_rows(intakes, runs, invoices)


def verify_rows(intakes, validation_rows, invoices):
    """The same source binding proof for database restore and customer import."""
    from collections import defaultdict
    runs_by_id = defaultdict(list)
    for run in validation_rows:
        runs_by_id[run["intake_id"]].append(run)
    count, validations = 0, 0
    for row in intakes:
        count += 1
        if not 0 < len(row["original"]) <= MAX_FILE or hashlib.sha256(row["original"]).hexdigest() != row["original_sha256"]:
            raise ValueError("Receipt original checksum mismatch")
        if row["xml"] is not None:
            if len(row["xml"]) > MAX_XML:
                raise ValueError("Receipt XML exceeds budget")
            reading = read(row["xml"], row["container"])
            if any(row["reading"].get(key) != value for key, value in reading.items()):
                raise ValueError("Receipt reading differs from XML")
            if row["container"] == "xml" and row["xml"] != row["original"]:
                raise ValueError("XML original differs from its reading source")
            if row["container"] == "pdf" and hashlib.sha256(row["xml"]).hexdigest() != row["reading"].get("embedded_sha256"):
                raise ValueError("Embedded XML checksum mismatch")
        runs = sorted(runs_by_id.pop(row["id"], []), key=lambda run: run["number"])
        if len(runs) != row["validation_number"]:
            raise ValueError("Incomplete validation history")
        for number, run in enumerate(runs, 1):
            validations += 1
            if run["number"] != number or run["original_sha256"] != row["original_sha256"] or hashlib.sha256(
                    run["report"].encode("utf-8")).hexdigest() != run["report_sha256"]:
                raise ValueError("Validation evidence mismatch")
        if row["state"] == "accepted":
            invoice = invoices.get(row["invoice_id"])
            if invoice is None or invoice["source_document_id"] != row["document_id"] or invoice["property_id"] != row["property_id"]:
                raise ValueError("Receipt invoice binding mismatch")
            if not runs or runs[-1]["state"] not in {"valid", "warning"} or row["blockers"]:
                raise ValueError("Accepted receipt lacks validation")
    if runs_by_id:
        raise ValueError("Orphan validation evidence")
    return {"intakes": count, "validations": validations}
