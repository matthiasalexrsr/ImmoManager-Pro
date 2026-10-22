"""Local manual-transfer worksheet; no guessed vendor field codes or XML writer.

The three hashes identify historical synthetic manufacturer originals. Their
field meanings are insufficient for a production serializer, even though their
envelope and actual field-key structure have been observed.
"""

import csv
import io
from collections import defaultdict
from typing import Any

from fastapi import HTTPException

from .tax_support import csv_cell

EVIDENCE_VERSION = "hv365-21.02.1530-observed-2026-v1"
BOUNDARY = (
    "Manueller Übertragungsbogen, keine importierbare WISO-Datei. Zielbezeichnungen wurden vom Nutzer geprüft; "
    "sie sind keine bestätigten Herstellerfeldnummern. Keine automatische AfA, Eigentümerquote oder Steuerrechtsprüfung."
)


def evidence_catalog():
    return {
        "version": EVIDENCE_VERSION, "target_product": "WISO Steuer Windows", "target_tax_year": 2026,
        "producer_product": "WISO Hausverwalter 365", "producer_version": "21.02.1530",
        "vendor_serializer_available": False, "target_import_verified": False,
        "observed_structure": {"root": "Elster", "header_version": "101", "declaration_version": "101",
            "form": "V", "object_attribute": "lfdNr", "field_attributes": ["nr", "index", "wert"]},
        "samples": [
            {"case": "baseline", "tax_year": 2026, "bytes": 4572,
                "sha256": "aa80c1780cca793440ae9b5a1ff18c33bcbef6a7dd249a49d1234b6b735b7c12",
                "object_field_counts": [34, 17]},
            {"case": "baseline", "tax_year": 2025, "bytes": 5094,
                "sha256": "7e786f35295a5a9b61747ca90cb7fb8d85f56d8e11f325c58a64b01b16119598",
                "object_field_counts": [36, 23]},
            {"case": "joint_afa_change", "tax_year": 2026, "bytes": 3437,
                "sha256": "aaaaa253466d08747a4463fbd505fad2c85dd5d135733ce938e094aa1d749b8b",
                "observed_fields": [{"nr": "0703418", "index": "1", "wert": "2.5"},
                    {"nr": "0703422", "index": "1", "wert": "1234,56"}],
                "isolated_field_meaning_verified": False},
        ],
        "missing_evidence": [
            "Kontrollierte Einzelfeldänderungen für Fachjahr 2026 mit Basis-/Änderungsoriginal, Build und Objektbezug.",
            "Vollständige fachliche Bedeutung je Formular/Feld/Index einschließlich Nullwerten, Erstattungen und mehreren Objekten.",
            "Annahme und Feld-/Centvergleich im echten WISO Steuer Windows für Fachjahr 2026.",
        ],
        "source_reference": "BUHL_PRODUCER_EVIDENCE.md (historische synthetische Herstellerexporte, 2026-10-01)",
        "boundary": BOUNDARY,
    }


def euro(cents):
    number = int(cents)
    return f"{'-' if number < 0 else ''}{abs(number) // 100},{abs(number) % 100:02}"


def prepare(profile, manifest):
    """Pure mapping of all existing groups, never another cash computation."""
    from .annual_tax_projection import fingerprint

    spec = profile["spec"]
    configuration = spec.get("wiso_preparation")
    if not configuration:
        return None
    objects = {item["property_id"]: item for item in configuration["objects"]}
    lines = {(item["treatment"], item["form_line"]): item for item in configuration["lines"]}
    issues: list[dict[str, Any]] = []
    if manifest["tax_year"] != 2026 or configuration["tax_year"] != 2026:
        issues.append({"code": "unsupported_tax_year"})
    if not manifest["ready"]:
        issues.append({"code": "annual_sources_unresolved"})
    if not manifest["full_year"]:
        issues.append({"code": "partial_year", "period_end": manifest["period_end"]})
    rows = []
    mapped_totals = {"income_cents": 0, "expense_cents": 0}
    unmapped_totals = {"income_cents": 0, "expense_cents": 0}
    used_objects, used_lines = set(), set()
    for group in manifest["groups"]:
        source_key = (group["treatment"], group["form_line"])
        obj, line = objects.get(group["property_id"]), lines.get(source_key)
        used_objects.add(group["property_id"])
        used_lines.add(source_key)
        missing = []
        if not obj:
            missing.append("object_mapping_missing")
        if not line:
            missing.append("target_label_missing")
        row = dict(group, object_number=obj["object_number"] if obj else None,
            target_object_label=obj["target_object_label"] if obj else None,
            target_label=line["target_label"] if line else None,
            review_reason=line["review_reason"] if line else None,
            amount_eur=euro(group["amount_cents"]), mapping_complete=not missing)
        rows.append(row)
        if missing:
            issues.append({"code": "mapping_incomplete", "property_id": group["property_id"],
                "treatment": group["treatment"], "form_line": group["form_line"], "missing": missing})
        target = unmapped_totals if missing else mapped_totals
        target[group["treatment"] + "_cents"] += int(group["amount_cents"])
    rows.sort(key=lambda row: (row["object_number"] is None, row["object_number"] or 0,
        row["property_id"], row["treatment"], row["form_line"]))
    reconciled = all(mapped_totals[key] + unmapped_totals[key] == int(manifest["totals"][key]) for key in mapped_totals)
    if not reconciled:
        raise HTTPException(503, "wiso_preparation_totals_integrity_failed: Die gespeicherte WISO-Vorbereitung ist beschädigt. Bitte Vollbackup und Schlüssel prüfen.")
    report = {"schema": "immomanager.wiso-manual-preparation.v1", "compatibility": "manual_transfer_only",
        "target_product": configuration["target_product"], "tax_year": manifest["tax_year"],
        "profile_version_id": profile["id"], "profile_sha256": profile["sha256"],
        "source_sha256": manifest["source_sha256"], "annual_preview_hash": manifest["preview_hash"],
        "evidence_version": configuration["evidence_version"], "period_end": manifest["period_end"],
        "full_year": manifest["full_year"], "vendor_file_ready": False, "target_import_verified": False,
        "manual_transfer_ready": not issues, "reconciled": reconciled, "issues": issues, "rows": rows,
        "mapped_totals": {key: str(value) for key, value in mapped_totals.items()},
        "unmapped_totals": {key: str(value) for key, value in unmapped_totals.items()},
        "unused_object_ids": sorted(set(objects) - used_objects),
        "unused_line_mappings": [{"treatment": kind, "form_line": name} for kind, name in sorted(set(lines) - used_lines)],
        "boundary": BOUNDARY, "evidence": evidence_catalog()}
    report["preparation_sha256"] = fingerprint(report)
    return report


OWNER_NOTE = ("Je Eigentümer nach den erfassten Eigentumsanteilen am Buchungstag (Eigentümer einer Buchung: "
              "ganz). Die Anteile ergeben je Zeile centgenau den Gesamtbetrag; keine Prüfung der steuerlichen Zurechnung.")


def owner_sheets(report, manifest):
    """Each owner's part of the rows, from the projection's owner split; outside the hashed report.

    The parts of one row add up to its amount to the cent, or the saved projection is damaged.
    """
    split = manifest.get("owner_split")
    if not split:
        return []
    rows = {(row["property_id"], row["treatment"], row["form_line"]): row for row in report["rows"]}
    sums: defaultdict[tuple, int] = defaultdict(int)
    sheets: dict[str | None, dict[str, Any]] = {}
    for part in split:
        key = (part["property_id"], part["treatment"], part["form_line"])
        row, value = rows.get(key), int(part["amount_cents"])
        if row is None:
            raise HTTPException(503, "wiso_preparation_owner_integrity_failed: Die gespeicherte WISO-Vorbereitung ist beschädigt. Bitte Vollbackup und Schlüssel prüfen.")
        sums[key] += value
        sheet = sheets.setdefault(part["owner_contact_id"], {"owner_contact_id": part["owner_contact_id"],
            "owner_name": part["owner_name"], "rows": [], "totals": {"income_cents": 0, "expense_cents": 0}})
        sheet["rows"].append({field: row[field] for field in ("object_number", "property_id", "property_name",
            "target_object_label", "treatment", "form_line", "target_label", "mapping_complete")}
            | {"amount_cents": str(value), "amount_eur": euro(value)})
        sheet["totals"][part["treatment"] + "_cents"] += value
    if any(sums.get(key, 0) != int(row["amount_cents"]) for key, row in rows.items()):
        raise HTTPException(503, "wiso_preparation_owner_integrity_failed: Die gespeicherte WISO-Vorbereitung ist beschädigt. Bitte Vollbackup und Schlüssel prüfen.")
    order = {key: index for index, key in enumerate(rows)}
    result = sorted(sheets.values(), key=lambda sheet: (sheet["owner_contact_id"] is None, sheet["owner_name"].casefold()))
    for sheet in result:
        sheet["rows"].sort(key=lambda row: order[(row["property_id"], row["treatment"], row["form_line"])])
        sheet["totals"] = {key: str(value) for key, value in sheet["totals"].items()}
        sheet["note"] = OWNER_NOTE
    return result


def saved_preparation(store, projection_id):
    """Validate retained originals and profile before exposing a historical sheet."""
    return saved_preparation_by_owner(store, projection_id)[0]


def saved_preparation_by_owner(store, projection_id):
    """The checked report and each owner's sheet (services.ownership; empty without owners)."""
    from . import annual_tax_storage as storage
    from .annual_tax_projection import canonical

    manifest = storage.read_projection(storage.projection_row(store, projection_id))
    profile = storage.get_profile(store, manifest["profile_version_id"])
    if profile["sha256"] != manifest["profile_sha256"]:
        raise HTTPException(503, "wiso_preparation_profile_integrity_failed: Die gespeicherte WISO-Vorbereitung ist beschädigt. Bitte Vollbackup und Schlüssel prüfen.")
    groups: dict[tuple, dict[str, Any]] = {}
    totals: defaultdict[str, int] = defaultdict(int)
    count = 0
    for record in storage.saved_sources(store, projection_id):
        count += 1
        if record["classification_state"] == "included":
            totals["cash_cents"] += int(record["booking"]["amount_cents"])
        for part in record["parts"]:
            amount = int(part["amount_cents"])
            kind = part["treatment"]
            if kind == "excluded":
                totals["excluded_cash_cents"] += amount
                continue
            amount = amount if kind == "income" else -amount
            totals[kind + "_cents"] += amount
            key = (part["property_id"], kind, part["form_line"])
            group = groups.setdefault(key, {"property_id": part["property_id"], "property_name": part["property_name"],
                "treatment": kind, "form_line": part["form_line"], "amount_cents": 0, "source_parts": 0})
            group["amount_cents"] += amount
            group["source_parts"] += 1
    expected_groups = [group | {"amount_cents": str(group["amount_cents"])} for _, group in sorted(groups.items())]
    if (count != manifest["source_rows"] or canonical(expected_groups) != canonical(manifest["groups"])
            or any(totals[key] != int(value) for key, value in manifest["totals"].items())):
        raise HTTPException(503, "wiso_preparation_source_integrity_failed: Die gespeicherte WISO-Vorbereitung ist beschädigt. Bitte Vollbackup und Schlüssel prüfen.")
    report = prepare(profile, manifest)
    if report is None:
        raise HTTPException(422, "wiso_preparation_profile_missing: Eine neue Profil-/Jahresfassung mit manuellen Zielzuordnungen erstellen.")
    if canonical(report) != canonical(manifest.get("wiso_preparation")):
        raise HTTPException(503, "wiso_preparation_snapshot_integrity_failed: Die gespeicherte WISO-Vorbereitung ist beschädigt. Bitte Vollbackup und Schlüssel prüfen.")
    return report, owner_sheets(report, manifest)


def worksheet_bytes(report):
    """Deterministic neutral CSV, with exact cents and explicit provenance."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(("tax_year", "object_number", "property_id", "source_object_name", "reviewed_target_object_label",
        "treatment", "source_form_line", "reviewed_manual_target_label", "amount_cents", "amount_eur",
        "source_parts", "mapping_complete", "review_reason", "profile_version_id", "source_sha256"))
    for row in report["rows"]:
        values = (report["tax_year"], row["object_number"], row["property_id"], row["property_name"], row["target_object_label"],
            row["treatment"], row["form_line"], row["target_label"], int(row["amount_cents"]),
            row["amount_eur"], row["source_parts"], row["mapping_complete"], row["review_reason"],
            report["profile_version_id"], report["source_sha256"])
        # Monetary strings are independently formatted numbers, not text input.
        writer.writerow([value if index == 9 else csv_cell(value) for index, value in enumerate(values)])
    return output.getvalue().encode("utf-8-sig")


def owner_worksheet_bytes(report, owners):
    """Each owner's rows in one CSV, exact cents, for filtering by owner in a spreadsheet."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(("tax_year", "owner_contact_id", "owner_name", "object_number", "property_id", "source_object_name",
        "reviewed_target_object_label", "treatment", "source_form_line", "reviewed_manual_target_label", "amount_cents",
        "amount_eur", "mapping_complete", "profile_version_id", "source_sha256"))
    for sheet in owners:
        for row in sheet["rows"]:
            values = (report["tax_year"], sheet["owner_contact_id"], sheet["owner_name"], row["object_number"], row["property_id"],
                row["property_name"], row["target_object_label"], row["treatment"], row["form_line"], row["target_label"],
                int(row["amount_cents"]), row["amount_eur"], row["mapping_complete"], report["profile_version_id"],
                report["source_sha256"])
            writer.writerow([value if index == 11 else csv_cell(value) for index, value in enumerate(values)])
    return output.getvalue().encode("utf-8-sig")
