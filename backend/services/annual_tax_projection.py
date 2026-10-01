"""Reviewed annual cash projection. This implements no tax law or vendor XML."""

import hashlib
import json
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from scripts.private_server_backup import private_workspace

from ..tax_models import AnnualTaxRule
from .annual_tax_source import cash_source, cents
from .portfolio_scope import current_scope, refresh_scope

SAMPLE_ROWS = 20  # Display samples; all sources are processed and retained.


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def cash_evidence(store, booking_id, portfolio_id):
    booking = store.get_booking(booking_id)
    account = store.get_account(booking.account_id)
    if account.portfolio_id != portfolio_id:
        raise HTTPException(422, "annual_tax_reference_portfolio: Der Gegen-/Korrekturbeleg muss zum selben Portfolio gehören.")
    return {"id": booking.id, "account_id": booking.account_id, "category_id": booking.category_id,
        "property_id": booking.property_id, "booking_date": booking.booking_date.isoformat(),
        "amount_cents": str(cents(booking.amount)), "status": booking.status,
        "updated_at": booking.updated_at.isoformat()}


def checked_parts(store, spec, entry, command, rules, overrides, pairs, property_cache):
    amount = cents(entry["amount"])
    override = overrides.get(entry["id"])
    rule = rules.get((entry["account_id"], entry["category_id"]))
    if override:
        parts = [item.model_dump() for item in override.parts]
        if sum(int(item["amount_cents"]) for item in parts) != amount:
            raise ValueError("allocation_sum_differs_from_cash")
        if any((int(item["amount_cents"]) > 0) != (amount > 0) for item in parts):
            raise ValueError("allocation_sign_differs_from_cash")
    else:
        if rule is None:
            raise ValueError("classification_missing")
        parts = [rule.model_dump(exclude={"account_id", "category_id"}) | {
            "amount_cents": str(amount), "property_id": entry["property_id"]}]
    for part in parts:
        identifier = part["property_id"]
        if part["treatment"] != "excluded" and not identifier:
            raise ValueError("property_assignment_required")
        if identifier:
            if identifier not in property_cache:
                prop = store.get_property(identifier)
                if prop.portfolio_id != spec["portfolio_id"]:
                    raise HTTPException(422, "annual_tax_property_portfolio: Das zugeordnete Objekt gehört zu einem anderen Portfolio.")
                property_cache[identifier] = {"id": prop.id, "name": prop.name}
            part["property_name"] = property_cache[identifier]["name"]
        else:
            part["property_name"] = None

    proof = {}
    if override and override.correction_of_booking_id:
        original = cash_evidence(store, override.correction_of_booking_id, spec["portfolio_id"])
        if (original["status"] != "confirmed" or original["booking_date"] > entry["booking_date"]
                or int(original["amount_cents"]) * amount >= 0):
            raise ValueError("correction_evidence_requires_earlier_opposite_cash")
        proof["correction_of"] = original
    if any(item["exclusion_kind"] == "internal_transfer" for item in parts):
        if any(item["exclusion_kind"] != "internal_transfer" for item in parts):
            raise ValueError("internal_transfer_requires_whole_booking")
        partner_id = pairs.get(entry["id"])
        if not partner_id:
            raise ValueError("internal_transfer_counter_evidence_required")
        partner = cash_evidence(store, partner_id, spec["portfolio_id"])
        if (partner["account_id"] == entry["account_id"] or partner["status"] != "confirmed"
                or int(partner["amount_cents"]) != -amount or partner["booking_date"] > command.as_of.isoformat()):
            raise ValueError("internal_transfer_requires_opposite_confirmed_other_account")
        partner_override = overrides.get(partner_id)
        partner_rule = rules.get((partner["account_id"], partner["category_id"]))
        partner_parts = partner_override.parts if partner_override else [partner_rule] if partner_rule else []
        if not partner_parts or any(item.treatment != "excluded" or item.exclusion_kind != "internal_transfer" for item in partner_parts):
            raise ValueError("internal_transfer_counter_must_also_be_excluded")
        proof["internal_transfer_counter"] = partner
    return parts, proof, override.reason if override else None


@dataclass
class CompiledProjection:
    manifest: dict
    sources: Path
    cleanup: ExitStack

    def close(self):
        self.cleanup.close()


def compile_projection(store, profile, command, *, parent=None):
    spec = profile["spec"]
    year, portfolio_id = spec["tax_year"], spec["portfolio_id"]
    if store.get_portfolio(portfolio_id).currency != spec["currency"]:
        raise HTTPException(422, "annual_tax_portfolio_currency_changed")
    if command.as_of < date(year, 1, 1) or command.as_of > date.today():
        raise HTTPException(422, "annual_tax_cash_cutoff: Der Stichtag muss im/ab Steuerjahr liegen und darf nicht in der Zukunft liegen.")
    cutoff = min(command.as_of, date(year, 12, 31))
    rules = {(rule["account_id"], rule["category_id"]): AnnualTaxRule(**rule) for rule in spec["rules"]}
    overrides = {item.booking_id: item for item in command.overrides}
    pairs: dict[str, str] = {}
    override_evidence: dict[str, dict] = {}
    for item in command.overrides:
        evidence = cash_evidence(store, item.booking_id, portfolio_id)
        if (evidence["booking_date"][:4] != f"{year:04}" or evidence["booking_date"] > cutoff.isoformat()
                or evidence["status"] != "confirmed"):
            raise HTTPException(422, "annual_tax_override_not_cash_source: Eine Aufteilung muss eine bestätigte Buchung bis zum Stichtag betreffen.")
        override_evidence[item.booking_id] = evidence
        if item.transfer_counter_booking_id:
            left, right = item.booking_id, item.transfer_counter_booking_id
            if left == right or (left in pairs and pairs[left] != right) or (right in pairs and pairs[right] != left):
                raise HTTPException(422, "annual_tax_ambiguous_transfer_pair: Ein Übertrag braucht ein eindeutiges Gegenpaar.")
            pairs[left], pairs[right] = right, left

    totals = dict(cash_cents=0, income_cents=0, expense_cents=0, excluded_cash_cents=0, unclassified_cash_cents=0)
    groups: dict[tuple, dict[str, Any]] = {}
    property_cache: dict[str, dict] = {}
    counts = dict(source_rows=0, confirmed_cash_rows=0, pending_rows=0, after_cutoff_rows=0, excluded_rows=0)
    issue_counts: defaultdict[str, int] = defaultdict(int)
    manifest = {"schema": "immomanager.annual-tax.v1", "compatibility": "vendor_neutral_reviewed_cash_projection",
        "portfolio_id": portfolio_id, "tax_year": year, "currency": "EUR", "profile_version_id": profile["id"],
        "profile_sha256": profile["sha256"], "cash_basis": "confirmed_bookings_once",
        "source_amount_basis": "signed_cash_gross_as_recorded",
        "period_start": date(year, 1, 1).isoformat(), "period_end": cutoff.isoformat(),
        "as_of": command.as_of.isoformat(), "full_year": cutoff == date(year, 12, 31),
        "blocking_issues": [], "source_samples": [], "pending_review_reason": command.pending_review_reason,
        "empty_cash_review_reason": command.empty_cash_review_reason,
        "tax_rule_source": "user_reviewed_classification", "generated_at": datetime.now(timezone.utc).isoformat()}
    cleanup, digest = ExitStack(), hashlib.sha256()
    seen = set()
    try:
        workspace, _ = cleanup.enter_context(private_workspace(parent))
        path = workspace / "sources.jsonl"
        with path.open("xb") as output, cash_source(store, portfolio_id, year) as source:
            for entry in source:
                counts["source_rows"] += 1
                identifier, state = entry["id"], "included"
                amount, parts, proof, reason = None, [], {}, None
                errors = []
                try:
                    amount = cents(entry["amount"])
                    if entry["status"] == "confirmed" and entry["booking_date"] <= cutoff.isoformat():
                        counts["confirmed_cash_rows"] += 1
                        totals["cash_cents"] += amount
                    if entry["category_id"] and entry["category_portfolio_id"] != portfolio_id:
                        raise ValueError("category_missing_or_cross_portfolio")
                    if entry["property_id"] and entry["property_portfolio_id"] != portfolio_id:
                        raise ValueError("property_missing_or_cross_portfolio")
                    if entry["booking_date"] > cutoff.isoformat():
                        state = "after_cutoff"
                        counts["after_cutoff_rows"] += 1
                    elif entry["status"] != "confirmed":
                        state = "pending"
                        counts["pending_rows"] += 1
                    else:
                        if identifier in overrides:
                            seen.add(identifier)
                            # Override proof came from the same current booking
                            # revision; refuse an independently changed source.
                            if override_evidence[identifier]["updated_at"] != entry["updated_at"]:
                                raise ValueError("override_cash_source_changed")
                        parts, proof, reason = checked_parts(store, spec, entry, command, rules, overrides, pairs, property_cache)
                except ValueError as error:
                    errors = [str(error)]
                    state = "needs_review"
                    if amount is not None and entry["status"] == "confirmed" and entry["booking_date"] <= cutoff.isoformat():
                        totals["unclassified_cash_cents"] += amount
                    issue_counts[str(error)] += 1
                    if len(manifest["blocking_issues"]) < SAMPLE_ROWS:
                        manifest["blocking_issues"].append({"code": str(error), "booking_id": identifier})
                for part in parts:
                    cash = int(part["amount_cents"])
                    kind = part["treatment"]
                    if kind == "excluded":
                        totals["excluded_cash_cents"] += cash
                        continue
                    effective = cash if kind == "income" else -cash
                    totals[kind + "_cents"] += effective
                    key = (part["property_id"], kind, part["form_line"])
                    group = groups.setdefault(key, {"property_id": part["property_id"], "property_name": part["property_name"],
                        "treatment": kind, "form_line": part["form_line"], "amount_cents": 0, "source_parts": 0})
                    group["amount_cents"] += effective
                    group["source_parts"] += 1
                if parts and all(item["treatment"] == "excluded" for item in parts):
                    counts["excluded_rows"] += 1
                record = {"booking": entry | {"amount_cents": str(amount) if amount is not None else None},
                    "classification_state": state, "parts": parts, "evidence": proof,
                    "override_reason": reason, "errors": errors}
                encoded = canonical(record) + b"\n"
                output.write(encoded)
                digest.update(encoded)
                if len(manifest["source_samples"]) < SAMPLE_ROWS:
                    manifest["source_samples"].append(record)
        if set(overrides) != seen:
            issue_counts["override_source_absent_from_snapshot"] += len(set(overrides) - seen)
        if counts["pending_rows"] and not command.pending_review_reason:
            issue_counts["pending_entries_need_explicit_review"] += counts["pending_rows"]
            manifest["blocking_issues"].append({"code": "pending_entries_need_explicit_review", "booking_id": None})
        if not counts["confirmed_cash_rows"] and not command.empty_cash_review_reason:
            issue_counts["no_confirmed_cash_sources"] += 1
            manifest["blocking_issues"].append({"code": "no_confirmed_cash_sources", "booking_id": None})
        reconciliation = totals["cash_cents"] == totals["income_cents"] - totals["expense_cents"] + totals["excluded_cash_cents"] + totals["unclassified_cash_cents"]
        if not reconciliation:
            raise HTTPException(503, "annual_tax_reconciliation_failed: Die Geldbeträge konnten nicht vollständig erhalten werden.")
        manifest.update(counts, totals={key: str(value) for key, value in totals.items()},
            groups=[group | {"amount_cents": str(group["amount_cents"])} for _, group in sorted(groups.items())],
            source_sha256=digest.hexdigest(), blocking_issue_counts=dict(issue_counts), ready=not issue_counts,
            cash_reconciled=reconciliation and "invalid_cash_amount" not in issue_counts,
            cash_totals_complete="invalid_cash_amount" not in issue_counts, tax_totals_complete=not issue_counts,
            note="Keine automatische AfA, Eigentümerquote oder Steuer-/WISO-Formularprüfung.")
        request = command.model_dump(mode="json", exclude={"preview_hash", "idempotency_key", "previous_projection_id", "revision_reason"})
        manifest["preview_hash"] = fingerprint({"profile": profile["sha256"], "source": manifest["source_sha256"],
            "request": request, "totals": manifest["totals"], "groups": manifest["groups"], "issues": manifest["blocking_issue_counts"]})
        refresh_scope(current_scope())
        return CompiledProjection(manifest, path, cleanup)
    except BaseException:
        cleanup.close()
        raise
