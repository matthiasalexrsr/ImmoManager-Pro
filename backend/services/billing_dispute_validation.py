"""Pure validation of retained dispute hashes, commands and parent bindings."""

from datetime import date
from typing import Mapping

from fastapi.encoders import jsonable_encoder

from .billing_dispute_types import AppendDisputeEvent, OpenDispute
from .measurement_history_validation import digest, payload


class DisputeIntegrityError(ValueError):
    pass


def event_hash(row, evidence):
    return digest({"event": {key: value for key, value in row.items() if key != "content_hash"},
                   "evidence": sorted(({"version_id": item["version_id"], "sha256": item["sha256"]}
                                      for item in evidence), key=lambda item: item["version_id"])})


def event_state(previous, kind):
    if kind == "opened" and previous is None:
        return "open"
    if kind == "reopened" and previous in {"withdrawn", "closed"}:
        return "open"
    if kind in {"withdrawn", "closed", "in_review"} and previous in {"open", "in_review"}:
        return kind
    if kind in {"note", "correction", "correction_link"} and previous is not None:
        return previous
    raise DisputeIntegrityError("Der bestätigte Prüfstand erlaubt dieses Ereignis nicht.")


def validate_event(row, evidence, case):
    if (not row["reason"].strip() or row["case_id"] != case["id"]
            or row["portfolio_id"] != case["portfolio_id"]
            or row["statement_revision"] != case["statement_revision"]
            or row["snapshot_hash"] != case["snapshot_hash"]
            or row["content_hash"] != event_hash(row, evidence)
            or len({item["version_id"] for item in evidence}) != len(evidence)
            or any(item["event_id"] != row["id"] or item["portfolio_id"] != case["portfolio_id"] for item in evidence)):
        raise DisputeIntegrityError("Widerspruchsoriginal ist beschädigt; Original und Wiederherstellung prüfen.")


def validate_dispute_snapshot(family, *, parents, verified_period_hashes: Mapping[str, str] | None = None):
    from ..db.billing_dispute_models import DISPUTE_TABLES
    from ..models import UtilityStatement
    if not set(DISPUTE_TABLES).intersection(family):
        return
    if not set(DISPUTE_TABLES).issubset(family):
        raise DisputeIntegrityError("Unvollständiges Widerspruchsjournal.")
    try:
        maps = {name: {row["id"]: row for row in family[name]} for name in DISPUTE_TABLES}
        if any(len(maps[name]) != len(family[name]) for name in DISPUTE_TABLES):
            raise ValueError("duplicate ids")
        cases, commands, events, evidence = (maps[name] for name in DISPUTE_TABLES)
        statements_by_period: dict[str, list] = {}
        for statement in parents["utility_statements"].values():
            statements_by_period.setdefault(statement["billing_period_id"], []).append(statement)
        period_hashes: dict[str, str] = {}
        def verified_statement(identifier):
            from .billing_originals import IMMUTABLE, snapshot_hash
            statement = parents["utility_statements"][identifier]
            period = parents["billing_periods"][statement["billing_period_id"]]
            if period["id"] not in period_hashes:
                if verified_period_hashes is not None:
                    # Internal native recovery hook: Root computes this from
                    # actual database bytes, never an HTTP/request payload.
                    period_hashes[period["id"]] = verified_period_hashes[period["id"]]
                else:
                    period_hashes[period["id"]] = snapshot_hash(
                        [UtilityStatement.model_validate(row) for row in statements_by_period[period["id"]]], period["owner_cost_share"])
            if (statement["status"] not in IMMUTABLE or period["status"] not in IMMUTABLE
                    or statement["snapshot_hash"] != period_hashes[period["id"]]):
                raise ValueError("finalized statement original")
            return statement
        if len({(row["actor_id"], row["idempotency_key"]) for row in commands.values()}) != len(commands):
            raise ValueError("duplicate command")
        if len({row["command_id"] for row in events.values()}) != len(events):
            raise ValueError("reused command receipt")
        by_case: dict[str, list[dict]] = {}
        by_event: dict[str, list[dict]] = {}
        for item in evidence.values():
            event = events[item["event_id"]]
            version = parents["document_versions"][item["version_id"]]
            case = cases[event["case_id"]]
            if (version["sha256"] != item["sha256"] or version["portfolio_id"] != case["portfolio_id"]
                    or version["property_id"] != case["property_id"]
                    or version.get("tenant_id") not in {None, case["tenant_id"]}
                    or version.get("contract_id") not in {None, case["contract_id"]}
                    or version.get("unit_id") not in {None, case["unit_id"]}):
                raise ValueError("evidence binding")
            by_event.setdefault(event["id"], []).append(item)
        for row in events.values():
            case = cases[row["case_id"]]
            validate_event(row, by_event.get(row["id"], []), case)
            command = commands[row["command_id"]]
            parsed = (OpenDispute if row["kind"] == "opened" else AppendDisputeEvent).model_validate(command["request"])
            if (command["case_id"] != case["id"] or command["revision"] != row["revision"]
                    or command["actor_id"] != row["actor_id"] or command["portfolio_id"] != case["portfolio_id"]
                    or command["request_hash"] != digest(command["request"])
                    or command["result"] != {"case_id": case["id"], "revision": row["revision"], "event_id": row["id"]}
                    or command["idempotency_key"] != parsed.idempotency_key or parsed.reason != row["reason"]
                    or parsed.preview_hash is None
                    or jsonable_encoder(command["created_at"]) != jsonable_encoder(row["created_at"])
                    or set(parsed.evidence_version_ids) != {link["version_id"] for link in by_event.get(row["id"], [])}):
                raise ValueError("command receipt")
            if isinstance(parsed, AppendDisputeEvent):
                if (parsed.kind != row["kind"] or parsed.corrects_event_id != row["corrects_event_id"]
                        or parsed.correction_statement_id != row["correction_statement_id"] or row["line_item_refs"]):
                    raise ValueError("command event references")
            elif (parsed.case_kind != case["case_kind"] or parsed.period_id != case["period_id"]
                    or parsed.statement_id != case["statement_id"]
                    or parsed.expected_statement_revision != case["statement_revision"]
                    or parsed.expected_snapshot_hash != case["snapshot_hash"]
                    or list(parsed.line_item_refs) != row["line_item_refs"]
                    or any(index >= len(case["original_snapshot"].get("line_items") or []) for index in parsed.line_item_refs)):
                raise ValueError("opening command binding")
            expected = parsed.expected_case_revision if isinstance(parsed, OpenDispute) else parsed.expected_revision
            observed = parsed.received_on if isinstance(parsed, OpenDispute) else parsed.observed_on
            if expected + 1 != row["revision"] or observed != date.fromisoformat(str(row["observed_on"])):
                raise ValueError("command revision")
            if row["corrects_event_id"]:
                original = events[row["corrects_event_id"]]
                if original["case_id"] != case["id"] or original["revision"] >= row["revision"] or row["kind"] != "correction":
                    raise ValueError("correction predecessor")
            if row["correction_statement_id"]:
                correction = verified_statement(row["correction_statement_id"])
                if (correction["snapshot_hash"] != row["correction_snapshot_hash"]
                        or correction["contract_id"] != case["contract_id"]
                        or correction["unit_id"] != case["unit_id"]
                        or parents["billing_periods"][correction["billing_period_id"]]["property_id"] != case["property_id"]):
                    raise ValueError("correction statement")
                seen = {correction["id"]}
                while correction["id"] != case["statement_id"]:
                    correction = parents["utility_statements"][correction["source_statement_id"]]
                    if correction["id"] in seen:
                        raise ValueError("correction cycle")
                    if correction["contract_id"] != case["contract_id"] or correction["unit_id"] != case["unit_id"]:
                        raise ValueError("correction chain party")
                    seen.add(correction["id"])
            elif row["correction_snapshot_hash"] is not None:
                raise ValueError("orphan correction hash")
            by_case.setdefault(case["id"], []).append(row)
        if len(commands) != len(events):
            raise ValueError("missing event")
        bound_statements = set()
        for case in cases.values():
            prop = parents["properties"][case["property_id"]]
            period = parents["billing_periods"][case["period_id"]]
            parents["portfolios"][case["portfolio_id"]]
            if (case["portfolio_id"] != prop["portfolio_id"] or period["property_id"] != prop["id"]
                    or case["original_hash"] != digest(case["original_snapshot"])):
                raise ValueError("case original")
            if case["case_kind"] == "tenant_statement":
                statement = verified_statement(case["statement_id"])
                unit = parents["units"][case["unit_id"]]
                contract = parents["contracts"][case["contract_id"]]
                parents["tenants"][case["tenant_id"]]
                if (case["statement_id"] in bound_statements or statement["billing_period_id"] != period["id"]
                        or statement["contract_id"] != case["contract_id"] or statement["unit_id"] != case["unit_id"]
                        or unit["property_id"] != prop["id"] or statement["revision"] != case["statement_revision"]
                        or contract["property_id"] != prop["id"] or contract["unit_id"] != unit["id"]
                        or contract["tenant_id"] != case["tenant_id"]
                        or statement["snapshot_hash"] != case["snapshot_hash"]
                        or case["original_snapshot"]["id"] != statement["id"]
                        or case["original_snapshot"] != UtilityStatement.model_validate(statement).model_dump(mode="json",
                            exclude={"status", "delivery_status", "delivered_at", "delivery_channel", "updated_at"})
                        or case["party_binding"] != "verified_at_case_opening"):
                    raise ValueError("statement binding")
                bound_statements.add(case["statement_id"])
            elif (case["case_kind"] != "property_review" or any(case[name] is not None for name in
                    ("statement_id", "statement_revision", "contract_id", "tenant_id", "unit_id"))
                    or case["original_snapshot"] != {"period_id": period["id"], "revision": period["revision_number"],
                        "owner_cost_share": jsonable_encoder(period["owner_cost_share"])}
                    or case["snapshot_hash"] != case["original_hash"] or case["party_binding"] != "no_tenant_property_review"):
                raise ValueError("property review binding")
            ordered = sorted(by_case.get(case["id"], []), key=lambda item: item["revision"])
            state, previous = None, None
            if len(ordered) != case["revision"] or any(row["revision"] != index + 1 for index, row in enumerate(ordered)):
                raise ValueError("event sequence")
            for row in ordered:
                if row["previous_hash"] != previous:
                    raise ValueError("hash chain")
                state = event_state(state, row["kind"])
                previous = row["content_hash"]
            if state != case["state"]:
                raise ValueError("derived state")
    except (KeyError, ValueError, TypeError) as error:
        raise DisputeIntegrityError("Widerspruchsjournal ist beschädigt; unveränderte Originale wiederherstellen.") from error


__all__ = ["DisputeIntegrityError", "digest", "payload", "event_hash", "event_state", "validate_event", "validate_dispute_snapshot"]
