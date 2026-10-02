"""Complete neutral CSV/JSON bundle from retained evidence, never today's books."""

import csv
import hashlib
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException

from scripts.private_server_backup import private_workspace

from .annual_tax_projection import canonical
from .annual_tax_storage import projection_row, read_projection, saved_sources
from .booking_export import csv_cell
from .portfolio_scope import current_scope, refresh_scope


@dataclass
class TaxDownload:
    path: Path
    cleanup: ExitStack
    sha256: str
    size: int

    def close(self):
        self.cleanup.close()


def prepare_download(store, projection_id, *, parent=None):
    manifest = read_projection(projection_row(store, projection_id))
    cleanup = ExitStack()
    try:
        workspace, _ = cleanup.enter_context(private_workspace(parent))
        source_path, cash_path, lines_path = (workspace / name for name in ("sources.jsonl", "cash-evidence.csv", "tax-lines.csv"))
        with source_path.open("xb") as original, cash_path.open("x", encoding="utf-8-sig", newline="") as cash:
            writer = csv.writer(cash, delimiter=";", lineterminator="\r\n")
            writer.writerow(("booking_id", "booking_date", "account_id", "account_name", "category_id", "property_id",
                "signed_cash_cents", "classification_state", "payment_text", "receipt_url", "override_reason", "treatment", "form_line",
                "part_cash_cents", "tax_income_or_expense_cents", "review_reason", "exclusion_kind"))
            totals = dict(cash_cents=0, income_cents=0, expense_cents=0, excluded_cash_cents=0, unclassified_cash_cents=0)
            count = 0
            for record in saved_sources(store, projection_id):
                count += 1
                original.write(canonical(record) + b"\n")
                booking, state = record["booking"], record["classification_state"]
                if state == "included":
                    totals["cash_cents"] += int(booking["amount_cents"])
                for part in record["parts"] or [None]:
                    value = int(part["amount_cents"]) if part else 0
                    tax_value = (value if part["treatment"] == "income" else -value) if part and part["treatment"] != "excluded" else 0
                    if part:
                        key = part["treatment"] + "_cents" if part["treatment"] != "excluded" else "excluded_cash_cents"
                        totals[key] += tax_value if part["treatment"] != "excluded" else value
                    raw = [booking["id"], booking["booking_date"], booking["account_id"], booking["account_name"], booking["category_id"],
                        part["property_id"] if part else booking["property_id"], int(booking["amount_cents"]), state,
                        booking["payment_text"], booking["receipt_url"], record["override_reason"], part["treatment"] if part else "",
                        part["form_line"] if part else "", value, tax_value, part["reason"] if part else manifest["pending_review_reason"] if state == "pending" else "cash cutoff",
                        part["exclusion_kind"] if part else ""]
                    writer.writerow([csv_cell(value) for value in raw])
        if count != manifest["source_rows"] or totals != {key: int(value) for key, value in manifest["totals"].items()}:
            raise HTTPException(503, "annual_tax_saved_totals_integrity_failed")
        with lines_path.open("x", encoding="utf-8-sig", newline="") as lines:
            writer = csv.writer(lines, delimiter=";", lineterminator="\r\n")
            writer.writerow(("tax_year", "property_id", "property_name", "treatment", "user_reviewed_form_line", "amount_cents", "source_parts"))
            for group in manifest["groups"]:
                writer.writerow([csv_cell(value) for value in (manifest["tax_year"], group["property_id"], group["property_name"], group["treatment"],
                    group["form_line"], int(group["amount_cents"]), group["source_parts"])])
        path = workspace / "annual-tax.zip"
        with ZipFile(path, "x", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for file_path in (source_path, cash_path, lines_path):
                archive.write(file_path, file_path.name)
            archive.writestr("manifest.json", canonical(manifest))
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise HTTPException(503, "annual_tax_archive_integrity_failed")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        refresh_scope(current_scope())
        return TaxDownload(path, cleanup, digest, path.stat().st_size)
    except BaseException:
        cleanup.close()
        raise
