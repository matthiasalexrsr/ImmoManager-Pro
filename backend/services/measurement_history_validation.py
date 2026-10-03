"""Pure snapshot validation shared by restore, privacy and source reads."""

import hashlib
import json
from typing import Any

from pydantic import TypeAdapter

from .measurement_history_types import FactData, MeasurementCommand

DATA: TypeAdapter = TypeAdapter(FactData)


class MeasurementIntegrityError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def payload(row) -> dict:
    if isinstance(row, dict):
        return dict(row)
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def fact_hash(row: dict, evidence: list[dict]) -> str:
    return digest({"fact": {key: value for key, value in row.items() if key != "content_hash"},
        "evidence": sorted(({"version_id": item["version_id"], "sha256": item["sha256"]}
                            for item in evidence), key=lambda item: item["version_id"])})


def validate_fact(row: dict, evidence: list[dict]) -> None:
    try:
        data = DATA.validate_python(row["data"])
        start = data.boundary_date if data.kind == "reading" else data.valid_from
        end = start if data.kind == "reading" else data.valid_until
        if (row["kind"] != data.kind or str(row["valid_from"]) != str(start)
                or str(row["valid_until"]) != str(end) or not row["reason"].strip()
                or row["content_hash"] != fact_hash(row, evidence)):
            raise ValueError("content")
        if row["withdrawn"] and not row["predecessor_id"]:
            raise ValueError("withdrawal")
        if data.kind == "proration" and not evidence:
            raise ValueError("approval evidence")
        for name in ("meter_id", "allocation_key_id", "contract_id"):
            if row[name] != getattr(data, name, None):
                raise ValueError("typed parent")
        if len({item["version_id"] for item in evidence}) != len(evidence):
            raise ValueError("duplicate evidence")
        for item in evidence:
            if item["fact_id"] != row["id"] or item["portfolio_id"] != row["portfolio_id"]:
                raise ValueError("evidence parent")
    except (ValueError, KeyError, TypeError) as error:
        raise MeasurementIntegrityError("Historische Quelle ist beschädigt; Original und Wiederherstellung prüfen.") from error


def validate_measurement_snapshot(family: dict[str, list[dict]], *, parents: dict[str, dict[str, dict]]) -> None:
    """Complete-family validator. Caller provides already scoped real parents.

    Required parent maps: units, properties, meters, allocation_keys, contracts,
    tenants, document_versions. No live reads or mutations are performed.
    """
    from ..db.measurement_history_models import MEASUREMENT_TABLES
    if not set(MEASUREMENT_TABLES).intersection(family):
        return
    if not set(MEASUREMENT_TABLES).issubset(family):
        raise MeasurementIntegrityError("Unvollständige historische Quellenfamilie.")
    try:
        maps = {name: {row["id"]: row for row in family[name]} for name in MEASUREMENT_TABLES}
        if any(len(maps[name]) != len(family[name]) for name in MEASUREMENT_TABLES):
            raise ValueError("duplicate ids")
        ledgers, commands, facts, evidence = (maps[name] for name in MEASUREMENT_TABLES)
        by_command: dict[str, list] = {}
        by_ledger: dict[str, list] = {}
        by_fact: dict[str, list] = {}
        for fact in facts.values():
            by_command.setdefault(fact["command_id"], []).append(fact)
            by_ledger.setdefault(fact["ledger_id"], []).append(fact)
        for link in evidence.values():
            by_fact.setdefault(link["fact_id"], []).append(link)
        command_keys, revisions, roots, successors = set(), set(), set(), set()
        for ledger in ledgers.values():
            unit = parents["units"][ledger["id"]]
            prop = parents["properties"][unit["property_id"]]
            if ledger["property_id"] != prop["id"] or ledger["portfolio_id"] != prop["portfolio_id"]:
                raise ValueError("ledger parent")
        for command in commands.values():
            ledger = ledgers[command["ledger_id"]]
            parsed = MeasurementCommand.model_validate(command["request"])
            marker = (command["actor_id"], command["idempotency_key"])
            revision = (ledger["id"], command["revision"])
            if (marker in command_keys or revision in revisions or command["portfolio_id"] != ledger["portfolio_id"]
                    or command["request_hash"] != digest(command["request"])
                    or parsed.expected_revision + 1 != command["revision"]
                    or parsed.idempotency_key != command["idempotency_key"]):
                raise ValueError("command")
            command_keys.add(marker)
            revisions.add(revision)
            children = sorted(by_command.get(command["id"], []), key=lambda r: r["position"])
            if ([item["position"] for item in children] != list(range(len(parsed.changes)))
                    or command["result"] != {"revision": command["revision"], "fact_ids": [item["id"] for item in children]}):
                raise ValueError("command result")
            for change, child in zip(parsed.changes, children, strict=True):
                if (child["source_key"] != change.source_key or child["predecessor_id"] != change.predecessor_id
                        or child["data"] != change.data.model_dump(mode="json")
                        or child["reason"] != change.reason or child["withdrawn"] != change.withdrawn
                        or set(change.evidence_version_ids) != {link["version_id"] for link in by_fact.get(child["id"], [])}):
                    raise ValueError("command facts")
        for ledger in ledgers.values():
            actual = sorted(revision for lid, revision in revisions if lid == ledger["id"])
            if actual != list(range(1, ledger["revision"] + 1)):
                raise ValueError("revision gap")
        for fact in facts.values():
            ledger, command = ledgers[fact["ledger_id"]], commands[fact["command_id"]]
            links = by_fact.get(fact["id"], [])
            validate_fact(fact, links)
            if (fact["portfolio_id"] != ledger["portfolio_id"] or fact["property_id"] != ledger["property_id"]
                    or command["ledger_id"] != ledger["id"] or fact["revision"] != command["revision"]):
                raise ValueError("fact parent")
            if fact["predecessor_id"]:
                previous = facts[fact["predecessor_id"]]
                if (previous["id"] in successors or previous["ledger_id"] != ledger["id"]
                        or previous["source_key"] != fact["source_key"] or previous["kind"] != fact["kind"]
                        or previous["revision"] >= fact["revision"]):
                    raise ValueError("predecessor")
                successors.add(previous["id"])
            else:
                marker = (ledger["id"], fact["source_key"])
                if marker in roots:
                    raise ValueError("duplicate root")
                roots.add(marker)
            for field, collection in (("meter_id", "meters"), ("allocation_key_id", "allocation_keys"), ("contract_id", "contracts")):
                if fact[field]:
                    parent = parents[collection][fact[field]]
                    if (field == "allocation_key_id" and parent["property_id"] != ledger["property_id"]
                            or field == "contract_id" and (parent["unit_id"] != ledger["id"] or parent["tenant_id"] != fact["tenant_id"])):
                        raise ValueError("retained subject")
            if fact["tenant_id"]:
                parents["tenants"][fact["tenant_id"]]
            for link in links:
                original = parents["document_versions"][link["version_id"]]
                if (original["sha256"] != link["sha256"] or original["portfolio_id"] != fact["portfolio_id"]
                        or original["property_id"] != fact["property_id"]
                        or original.get("unit_id") not in (None, ledger["id"])):
                    raise ValueError("document original")
        if any(link["fact_id"] not in facts for link in evidence.values()):
            raise ValueError("orphan evidence")
        for ledger in ledgers.values():
            validate_effective([fact for fact in by_ledger.get(ledger["id"], []) if fact["id"] not in successors])
        assigned: dict[str, list] = {}
        for fact in facts.values():
            if fact["kind"] == "assignment" and fact["id"] not in successors and not fact["withdrawn"]:
                assigned.setdefault(fact["meter_id"], []).append(DATA.validate_python(fact["data"]))
        for assignments in assigned.values():
            ordered = sorted(assignments, key=lambda row: (row.valid_from, row.valid_until))
            if any(left.valid_until > right.valid_from for left, right in zip(ordered, ordered[1:])):
                raise ValueError("overlapping physical meter across units")
    except (KeyError, TypeError, ValueError) as error:
        raise MeasurementIntegrityError("Historische Quellenfamilie ist unvollständig oder widersprüchlich.") from error


def validate_effective(rows: list[dict]) -> None:
    """Local timeline consistency; incomplete evidence may be saved for repair."""
    current = {row["source_key"]: DATA.validate_python(row["data"]) for row in rows if not row["withdrawn"]}
    by_id = {row["id"]: DATA.validate_python(row["data"]) for row in rows if not row["withdrawn"] and "id" in row}
    intervals: dict[tuple, list] = {}
    readings = set()
    for data in current.values():
        if data.kind in {"reading", "proration"}:
            assignment = current.get(data.assignment_key)
            if assignment is None or assignment.kind != "assignment":
                raise MeasurementIntegrityError("Ablesung/Freigabe benötigt eine wirksame Zählerzuordnung.")
            first = data.boundary_date if data.kind == "reading" else data.valid_from
            last = first if data.kind == "reading" else data.valid_until
            if not assignment.valid_from <= first <= last <= assignment.valid_until:
                raise MeasurementIntegrityError("Ablesung/Freigabe liegt außerhalb der belegten Zählerbetriebszeit.")
            if data.kind == "proration":
                left, right = by_id.get(data.start_reading_id), by_id.get(data.end_reading_id)
                if (left is None or right is None or left.kind != "reading" or right.kind != "reading"
                        or left.assignment_key != data.assignment_key or right.assignment_key != data.assignment_key
                        or left.boundary_date != first or right.boundary_date != last or left.value > right.value):
                    raise MeasurementIntegrityError("Zeitfreigabe benötigt die noch wirksamen Originalablesungen an beiden genannten Grenzen.")
        if data.kind == "reading":
            reading_marker = (data.assignment_key, data.boundary_date)
            if reading_marker in readings:
                raise MeasurementIntegrityError("Eine Grenzablesung benötigt eine eindeutige Quellenreihe; vorhandenen Wert korrigieren.")
            readings.add(reading_marker)
            continue
        markers = [("occupancy",)] if data.kind == "occupancy" else (
            [("meter", data.meter_id), ("circuit", data.circuit_path)] if data.kind == "assignment" else
            [("selection", data.allocation_key_id)] if data.kind == "selection" else [("proration", data.assignment_key)])
        for interval_marker in markers:
            intervals.setdefault(interval_marker, []).append(data)
    for group in intervals.values():
        ordered = sorted(group, key=lambda item: (item.valid_from, item.valid_until))
        if any(left.valid_until > right.valid_from for left, right in zip(ordered, ordered[1:])):
            raise MeasurementIntegrityError("Historische Zeitabschnitte derselben Grundlage überschneiden sich.")
