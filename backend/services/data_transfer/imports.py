"""Preview, recheck and atomically merge a reviewed customer migration batch."""
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import uuid4, uuid5

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import insert, select

from ...data_transfer_models import BatchOptions, CommitImport, PreviewChange
from ...db.data_transfer_models import ExternalReferenceORM as Reference
from ...db.data_transfer_models import ImportBatchORM as Batch
from ...db.data_transfer_models import ImportFileORM as File
from ...db.document_version_models import DocumentVersionORM
from ...domain.lease_engine import find_unit_overlap, unit_overlap_message
from .. import data_snapshot as snapshots
from ..integrations import connection_storage as db
from . import csv_templates as csv
from .common import digest, encoded, lock_target, work

MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
VOLATILE = {"created_at", "updated_at"}


def _active_models():
    from .portable_archive import ACTIVE_MODELS
    return ACTIVE_MODELS


def _files(unit, identifier):
    if unit.db is not None:
        return list(unit.db.scalars(select(File).where(File.batch_id == identifier).order_by(File.filename)))
    return sorted((f for f in db.memory(unit, File).values() if f.batch_id == identifier), key=lambda f: f.filename)


def _references(unit, batch):
    if unit.db is not None:
        rows = unit.db.scalars(select(Reference).where(Reference.portfolio_id == batch.portfolio_id, Reference.source_system == batch.source_system))
    else:
        rows = (row for row in db.memory(unit, Reference).values() if row.portfolio_id == batch.portfolio_id and row.source_system == batch.source_system)
    return {row.id: row for row in rows}


def public(batch):
    return {key: getattr(batch, key) for key in ("id", "portfolio_id", "source_system", "format", "state", "revision",
        "mappings", "preview", "target_sha256", "plan_sha256", "result", "created_at", "updated_at")}


def listing(store, actor_id, *, skip=0, limit=25):
    with work(store, actor_id) as unit:
        if unit.db is not None:
            from sqlalchemy import func
            total = unit.db.scalar(select(func.count()).select_from(Batch))
            rows = unit.db.scalars(select(Batch).order_by(Batch.created_at.desc(), Batch.id).offset(skip).limit(limit))
        else:
            all_rows = sorted(db.memory(unit, Batch).values(), key=lambda row: (row.created_at, row.id), reverse=True)
            total, rows = len(all_rows), all_rows[skip:skip + limit]
        return {"items": [{key: getattr(row, key) for key in ("id", "state", "revision", "source_system", "format", "created_at")} for row in rows],
                "total": total, "skip": skip, "limit": limit}


def detail(store, actor_id, identifier):
    with work(store, actor_id) as unit:
        return public(db.row(unit, Batch, identifier))


def _target(unit):
    backend = snapshots._backend(unit.store)
    records = {spec.key: {row.id: row for row in backend.records(spec)} for spec in snapshots.entity_specs()}
    values = {table: [row.model_dump(mode="json") for row in sorted(rows.values(), key=lambda row: row.id)]
              for table, rows in records.items()}
    if unit.db is not None:
        versions = [list(row) for row in unit.db.execute(select(DocumentVersionORM.id, DocumentVersionORM.sha256,
            DocumentVersionORM.number, DocumentVersionORM.document_id).order_by(DocumentVersionORM.id))]
    else:
        versions = [[row.id, row.sha256, row.number, row.document_id] for row in sorted(unit.archive.versions.values(), key=lambda row: row.id)]
    evidence = {}
    for model in _active_models():
        rows = unit.db.scalars(select(model).order_by(model.id)) if unit.db is not None else sorted(db.memory(unit, model).values(), key=lambda row: row.id)
        evidence[model.__tablename__] = [{column.name: hashlib.sha256(value).hexdigest() if isinstance(value := getattr(row, column.name), bytes)
            else value.isoformat() if hasattr(value, "isoformat") else value for column in model.__table__.columns} for row in rows]
    return records, digest({"business": values, "original_versions": versions, "evidence": evidence})


def _plain(record):
    return {key: value for key, value in record.model_dump(mode="json").items() if key not in VOLATILE}


def _load(unit, batch, files, existing):
    payload: dict = {}
    references, metadata, errors, warnings = [], [], [], []
    options = batch.mappings
    mappings = options.get("columns", {})
    mapped = options.get("references", {})
    for reference, identifier in mapped.items():
        table, separator, external = reference.partition(":")
        if not separator or not external or table not in existing or identifier not in existing[table]:
            errors.append("Ungültige bestehende Referenzzuordnung: " + reference)
    for file in files:
        if hashlib.sha256(file.content).hexdigest() != file.sha256:
            errors.append("Die gespeicherte Quelldatei ist beschädigt: " + file.filename)
            continue
        if file.entity in ("snapshot", "portability"):
            try:
                if file.entity == "portability":
                    from .portable_archive import read
                    source, _, _, _, _ = read(file.content)
                    warnings.append("Kundenexport: frühere Bankfreigaben bleiben historische Nachweise. Empfänger und Zahlungsvorschläge sind erneut freizugeben; offene E-Rechnungen sind lokal erneut zu prüfen.")
                else:
                    source = json.loads(file.content.decode("utf-8-sig"))
                encoded(source)
                if not isinstance(source, dict):
                    raise ValueError("JSON-Objekt erwartet")
                known = {spec.key for spec in snapshots.entity_specs()} | {a for aliases in snapshots._KEY_ALIASES.values() for a in aliases}
                if not known.intersection(source):
                    raise ValueError("Keine ImmoManager-Geschäftsdaten")
                payload = source
                metadata.append({"filename": file.filename, "entity": file.entity, "sha256": file.sha256})
            except (ValueError, UnicodeError, RecursionError) as error:
                errors.append("Ungültige ImmoManager-Datei: " + str(error)[:300])
            continue
        try:
            headers, mapping, rows = csv.parse(file.content, file.entity, mappings.get(file.filename))
            metadata.append({"filename": file.filename, "entity": file.entity, "sha256": file.sha256, "headers": headers,
                "mapping": mapping, "rows": len(rows), "sample": [row for _, row in rows[:10]]})
            for number, row in rows:
                try:
                    output = csv.convert(file.entity, row, batch.portfolio_id, batch.source_system, existing_refs=mapped)
                    reuse = output[0][0] + ":" + row["external_ref"] in mapped
                    for table, value in output:
                        primary = table == output[0][0]
                        if primary and reuse:
                            warnings.append(f"{file.filename}, Zeile {number}: {table} {value['id']} wird ausdrücklich als bestehender Datensatz unverändert verwendet.")
                        elif not reuse:
                            payload.setdefault(table, []).append(value)
                        if primary:
                            references.append({"entity": table, "external_ref": row["external_ref"], "record_id": value["id"],
                                               "source_sha256": digest(row)})
                except (ValueError, TypeError, KeyError) as error:
                    errors.append(f"{file.filename}, Zeile {number}: {error}")
        except ValueError as error:
            # Keep selectable source headers even when mandatory mappings are missing.
            try:
                _, headers = csv.reader_for(file.content)
            except ValueError:
                headers = []
            metadata.append({"filename": file.filename, "entity": file.entity, "sha256": file.sha256,
                             "headers": headers, "mapping": mappings.get(file.filename, {}), "rows": None, "sample": []})
            errors.append(f"{file.filename}: {error}")
    return payload, references, metadata, errors, warnings


def _normalize(batch, payload):
    normalized = dict(payload)
    for spec in snapshots.entity_specs():
        source = payload.get(spec.key, next((payload[alias] for alias in snapshots._KEY_ALIASES.get(spec.key, ()) if alias in payload), None))
        if not isinstance(source, list):
            continue  # prepare_import supplies the useful format diagnostic.
        normalized[spec.key] = [{**row, "id": row.get("id") or str(uuid5(csv.NAMESPACE, f"{batch.id}:{spec.key}:{index}")),
            **{field: row.get(field) or batch.created_at.isoformat() for field in VOLATILE if field in spec.model.model_fields}}
            if isinstance(row, dict) else row for index, row in enumerate(source)]
    return normalized


def _duplicates(payload, existing):
    errors, warnings, duplicates = [], [], []
    keys = {"properties": ("name", "address_line", "postal_code", "city"), "units": ("property_id", "label"),
            "tenants": ("full_name", "email"), "contacts": ("first_name", "last_name", "company_name", "email")}
    for spec in snapshots.entity_specs():
        raw = payload.get(spec.key, [])
        if not isinstance(raw, list):
            continue
        index = defaultdict(list)
        fields = keys.get(spec.key)
        def natural(record):
            return tuple(" ".join(str(getattr(record, key, "") or "").casefold().split()) for key in fields or ())
        if fields:
            for existing_record in existing[spec.key].values():
                index[natural(existing_record)].append(existing_record.id)
        for item in raw:
            try:
                record: Any = spec.model.model_validate(item)
            except ValidationError:
                continue
            old = existing[spec.key].get(record.id)
            if old:
                same = _plain(old) == _plain(record)
                duplicates.append({"entity": spec.key, "id": record.id, "same": same})
                if not same:
                    errors.append(f"{spec.key} {record.id}: Die gleiche ID enthält abweichende Daten; bestehende Datensätze werden nicht überschrieben.")
            elif fields and any(natural(record)):
                matches = index[natural(record)]
                if matches:
                    warnings.append(f"Mögliche Dublette in {spec.key}: {record.id}; vorhandene Referenz(en): {', '.join(matches[:5])}.")
                index[natural(record)].append(record.id)
    return errors, warnings, duplicates


def _relationships(prepared, existing):
    final = {name: dict(records) for name, records in existing.items()}
    for spec, rows in prepared.plan:
        final[spec.key].update((row.id, row) for row in rows)
    units = final.get("units", {})
    contracts = defaultdict(list)
    for contract in final.get("contracts", {}).values():
        contracts[contract.unit_id].append(contract)
    errors = []
    for spec, rows in prepared.plan:
        for row in rows:
            unit_id, property_id = getattr(row, "unit_id", None), getattr(row, "property_id", None)
            if unit_id and property_id and unit_id in units and units[unit_id].property_id != property_id:
                errors.append(f"{spec.key} {row.id}: Einheit und Immobilie gehören nicht zusammen.")
            if spec.key == "contracts":
                clash = find_unit_overlap(row, contracts[row.unit_id], exclude_id=row.id)
                if clash:
                    errors.append(f"Vertrag {row.contract_number}: {unit_overlap_message(clash)}")
            if spec.key == "accounts" and row.owner_contact_id:
                owner = final.get("contacts", {}).get(row.owner_contact_id)
                if owner is None or owner.contact_type != "owner":
                    errors.append(f"Konto {row.name}: Die Eigentümerzuordnung muss auf eine Eigentümerpartei zeigen.")
    return errors


def _controls(plan):
    totals = {}
    monetary = {"accounts": ("opening_balance",), "receivables": ("amount_due",), "invoices": ("net_amount", "vat_amount", "gross_amount"),
                "contracts": ("deposit_amount",), "contract_rent_periods": ("cold_rent", "service_charge_advance", "heating_advance")}
    for spec, rows in plan:
        if rows:
            totals[spec.key] = {"count": len(rows), "amounts": {field: format(sum(
                (Decimal(str(getattr(row, field, None) or 0)) for row in rows), Decimal(0)), ".2f") for field in monetary.get(spec.key, ())}}
    return totals


def _preview(unit, batch, files):
    existing, target_sha = _target(unit)
    payload, references, metadata, errors, warnings = _load(unit, batch, files, existing)
    payload = _normalize(batch, payload)
    duplicate_errors, duplicate_warnings, duplicates = _duplicates(payload, existing)
    errors.extend(duplicate_errors)
    warnings.extend(duplicate_warnings)
    registered = _references(unit, batch)
    for reference in references:
        identifier_ref = csv.identifier(batch.portfolio_id, batch.source_system, "reference:" + reference["entity"], reference["external_ref"])
        previous = registered.get(identifier_ref)
        if previous and previous.record_id != reference["record_id"]:
            errors.append("Externe Referenz bereits anders zugeordnet: " + reference["entity"] + ":" + reference["external_ref"])
    prepared = None
    try:
        prepared = snapshots.prepare_import(unit.store, payload, replace=False)
        errors.extend(_relationships(prepared, existing))
        for file in files:
            if file.entity == "portability":
                from .portable_import import prepare
                try:
                    prepared.portability_plan = prepare(unit, file.content, prepared)
                except (ValueError, TypeError, KeyError) as error:
                    errors.append("Kundenexport: " + str(error)[:300])
    except snapshots.SnapshotError as error:
        errors.extend(error.problems)
    # Bind also to the reviewed reference map; otherwise a changed mapping could
    # import the same counts into a different household without a new decision.
    plan_hash = digest({"payload": payload, "mappings": batch.mappings, "source_files": [(file.filename, file.sha256) for file in files]})
    preview = {"files": metadata, "errors": errors[:100], "error_count": len(errors), "warnings": warnings[:100],
        "warning_count": len(warnings), "duplicates": duplicates[:100], "duplicate_count": len(duplicates),
        "controls": _controls(prepared.plan) if prepared else {}, "skipped_existing": prepared.skipped if prepared else {},
        "document_versions": len(prepared.fresh_originals) if prepared else 0,
        "sample": {spec.key: [row.model_dump(mode="json") for row in rows[:5]] for spec, rows in prepared.plan if rows} if prepared else {}}
    if prepared is not None and prepared.portability_plan:
        active, history, assets = prepared.portability_plan
        preview["additional_evidence"] = {"active_records": len(active), "historical_proofs": len(history), "attachments": len(assets),
            "attachment_sha256": [{"path": key, "sha256": hashlib.sha256(raw).hexdigest()} for key, raw in assets][:100]}
    return preview, target_sha, plan_hash, prepared, references


def create(store, actor_id, files, options: BatchOptions, key):
    if not 16 <= len(key) <= 100 or not 1 <= len(files) <= 6 or sum(len(content) for _, content in files) > MAX_TOTAL:
        raise HTTPException(422, "Ungültige Wiederholungskennung oder Dateimenge (1–6 Dateien, zusammen höchstens 128 MiB).")
    named = []
    for filename, content in files:
        if not filename or len(filename) > 200 or any(char in filename for char in "\\/\x00") or not content or len(content) > MAX_FILE:
            raise HTTPException(422, "Ungültiger Dateiname, leere Datei oder Datei größer als 64 MiB.")
        entity = "snapshot" if filename.lower().endswith(".json") else "portability" if filename.lower().endswith(".zip") else filename[:-4] if filename.endswith(".csv") else ""
        if entity not in csv.SCHEMAS and entity not in ("snapshot", "portability"):
            raise HTTPException(422, "CSV-Dateinamen müssen der Vorlage entsprechen, zum Beispiel units.csv.")
        named.append((filename, content, entity))
    if len({name for name, _, _ in named}) != len(named) or (any(entity in ("snapshot", "portability") for _, _, entity in named) and len(named) != 1):
        raise HTTPException(422, "Doppelte Dateinamen oder gemischte CSV-/Snapshot-Übernahme sind nicht zulässig.")
    format_name = named[0][2] if named[0][2] in ("snapshot", "portability") else "csv"
    if format_name == "csv" and not options.portfolio_id:
        raise HTTPException(422, "Für CSV-Dateien muss ein Zielbestand ausgewählt werden.")
    request_hash = digest({"files": [(name, hashlib.sha256(content).hexdigest()) for name, content, _ in named], **options.model_dump()})
    with work(store, actor_id, write=True) as unit:
        previous = db.find_one(unit, Batch, created_by=actor_id, idempotency_key=key)
        if previous:
            if previous.request_sha256 != request_hash:
                raise HTTPException(409, "Diese Wiederholungskennung gehört zu einer anderen Übernahme.")
            return public(previous)
        if options.portfolio_id:
            unit.store.get_portfolio(options.portfolio_id)
        batch = db.put(unit, Batch, {"id": str(uuid4()), "portfolio_id": options.portfolio_id, "source_system": options.source_system,
            "format": format_name, "created_by": actor_id, "idempotency_key": key, "request_sha256": request_hash,
            "state": "preview", "revision": 1, "mappings": {"columns": options.columns, "references": options.references},
            "preview": {}, "target_sha256": "", "plan_sha256": "", "accepted_key": None, "accepted_sha256": None,
            "result": None, "created_at": db.now(), "updated_at": db.now()})
        for filename, content, entity in named:
            db.put(unit, File, {"id": str(uuid4()), "batch_id": batch.id, "filename": filename, "entity": entity,
                "sha256": hashlib.sha256(content).hexdigest(), "content": content})
        preview, target_sha, plan_sha, _, _ = _preview(unit, batch, _files(unit, batch.id))
        return public(db.put(unit, Batch, {**db.values(batch), "preview": preview, "state": "invalid" if preview["error_count"] else "ready",
                                         "target_sha256": target_sha, "plan_sha256": plan_sha}))


def repreview(store, actor_id, identifier, command: PreviewChange):
    request_hash = digest({"action": "preview", **command.model_dump()})
    with work(store, actor_id, write=True) as unit:
        batch = db.row(unit, Batch, identifier, lock=True)
        if batch.accepted_key == command.idempotency_key and batch.accepted_sha256 == request_hash:
            return public(batch)
        db.revision(batch, command.expected_revision)
        if batch.state == "committed":
            raise HTTPException(409, "Diese Übernahme wurde bereits abgeschlossen.")
        batch = db.put(unit, Batch, {**db.values(batch), "mappings": {"columns": command.columns, "references": command.references}})
        preview, target_sha, plan_sha, _, _ = _preview(unit, batch, _files(unit, identifier))
        return public(db.put(unit, Batch, {**db.values(batch), "preview": preview, "state": "invalid" if preview["error_count"] else "ready",
            "target_sha256": target_sha, "plan_sha256": plan_sha, "revision": batch.revision + 1,
            "accepted_key": command.idempotency_key, "accepted_sha256": request_hash, "updated_at": db.now()}))


def commit(store, actor_id, identifier, command: CommitImport):
    request_hash = digest({"action": "commit", **command.model_dump()})
    with work(store, actor_id, write=True) as unit:
        batch = db.row(unit, Batch, identifier, lock=True)
        if batch.state == "committed" and batch.accepted_key == command.idempotency_key and batch.accepted_sha256 == request_hash:
            return public(batch)
        db.revision(batch, command.expected_revision)
        if batch.state != "ready":
            raise HTTPException(409, "Zuerst alle Fehler in der Vorschau beheben.")
        from types import SimpleNamespace
        lock_target(unit, [*snapshots.entity_specs(), *[SimpleNamespace(table=model.__table__) for model in (*_active_models(), DocumentVersionORM)]])
        preview, target_sha, plan_sha, prepared, references = _preview(unit, batch, _files(unit, identifier))
        if target_sha != batch.target_sha256 or plan_sha != batch.plan_sha256 or preview["error_count"] or prepared is None:
            raise HTTPException(409, "Der Zielbestand oder die Quelldaten haben sich geändert. Nichts wurde übernommen; bitte die Vorschau erneuern.")
        if preview["warning_count"] and not command.acknowledge_warnings:
            raise HTTPException(422, "Die Hinweise und möglichen Dubletten müssen ausdrücklich geprüft werden.")
        result = prepared.apply_in_unit(unit)
        if prepared.portability_plan is not None:
            from .portable_import import apply
            apply(unit, batch, prepared.portability_plan)
        registered, fresh = _references(unit, batch), []
        for reference in references:
            identifier_ref = csv.identifier(batch.portfolio_id, batch.source_system, "reference:" + reference["entity"], reference["external_ref"])
            previous = registered.get(identifier_ref)
            if previous and previous.record_id != reference["record_id"]:
                raise HTTPException(409, "Eine externe Referenz ist bereits anders zugeordnet. Nichts wurde übernommen.")
            if not previous:
                value = {"id": identifier_ref, "portfolio_id": batch.portfolio_id, "source_system": batch.source_system,
                    **reference, "batch_id": batch.id, "created_at": db.now()}
                fresh.append(value)
                registered[identifier_ref] = Reference(**value)
        if unit.db is not None and fresh:
            unit.db.execute(insert(Reference), fresh)
        elif unit.db is None:
            for value in fresh:
                db.put(unit, Reference, value)
        return public(db.put(unit, Batch, {**db.values(batch), "state": "committed", "revision": batch.revision + 1,
            "accepted_key": command.idempotency_key, "accepted_sha256": request_hash,
            "result": {**result, "controls": preview["controls"], "reason": command.reason, "committed_by": actor_id}, "updated_at": db.now()}))
