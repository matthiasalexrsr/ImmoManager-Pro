"""Lossless JSON snapshots of the business data: export, import and restore.

The entity list is derived from the database schema (every business table the
in-memory store mirrors), so new tables are covered without touching this
module. Records keep their IDs, which keeps every reference between them
intact, and a snapshot is validated completely before anything is written:

* merge (import): records whose ID already exists are skipped, so importing
  the same file twice changes nothing;
* replace (restore): the business data is swapped all or nothing.

Finalized utility statements are checked against their snapshot hash: a file
whose issued statements were edited, or a merge that would add statements or
costs to an issued period, is refused.

User accounts, sessions and the audit log are not part of a snapshot. Archived
document originals are, with their bytes (see document_original_snapshot).
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Table, UniqueConstraint, select

from ..config import settings
from ..db.orm_models import Base
from ..storage import InMemoryStore
from . import document_original_snapshot as originals
from .final_statements import FINAL_STATUSES, final_version_problems

SNAPSHOT_FORMAT = "immomanager-snapshot"
# 3: archived document originals (older versions would drop them, so they refuse the file)
# 4: service contracts and the origin of transferred costs (likewise)
# 5: invoice reviews, their immutable history and cost transfers (likewise)
# 6: dunning cases, letters, outbox, replies, blocks, disputes, settings (likewise)
# 7: deposit file: instalments, payments, interest rates, settlements (likewise)
# 8: shared conversation notes, reversible commands and document intake (likewise)
# 9: canonical receivable settlement links; private saved reports are full-backup only
# 10: document recovery/evidence records, joined with the canonical finance contract
# 11: re-letting projects, applicant details and their documents (likewise)
# 12: document expiry dates and reminder lead times (likewise)
# 13: the retention class chosen on a document (likewise)
# 14: a tenant's direct debit account and mandate date (likewise)
# 15: owners' shares of properties and units, their changes and the owner a booking belongs to (likewise)
# 16: explicitly disclosed invoice payable rounding (never folded into VAT)
SNAPSHOT_FORMAT_VERSION = 16

# Keys used by exports written before format 2.
_KEY_ALIASES = {"viewing_appointments": ("viewings",)}
_MAX_REPORTED_PROBLEMS = 20


class SnapshotError(ValueError):
    """The snapshot cannot be applied; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        shown = "; ".join(problems[:_MAX_REPORTED_PROBLEMS])
        more = len(problems) - _MAX_REPORTED_PROBLEMS
        suffix = f" (und {more} weitere)" if more > 0 else ""
        super().__init__(f"{len(problems)} Problem(e), nichts wurde geändert: {shown}{suffix}")


def _require_full_bank_backup(store: Any) -> None:
    from ..db.bank_models import BankImportORM
    if hasattr(store, 'db'):
        present = store.db.scalar(select(BankImportORM.id).limit(1)) is not None
    else:
        present = bool(store.__dict__.get('_integration_connections', {}).get('bank_imports'))
    if present:
        raise SnapshotError(['Dieser Bestand enthält geschützte Bankoriginale. Bitte die vollständige Sicherung mit Datenbank und Schlüsselring verwenden; JSON kann diese Quellen nicht verlustfrei wiederherstellen.'])
    _require_full_private_backup(store)


def _require_full_private_backup(store: Any) -> None:
    """A partial business snapshot cannot replace private workflow evidence."""
    prefixes = ('integration_', 'communication_', 'teha_', 'channel_', 'assistant_', 'e_invoice_')
    payment_evidence = frozenset({'payment_recipient_versions', 'payment_authorizations', 'payment_security_settings',
                                  'payment_totp_uses', 'payment_security_events', 'payment_totp_attempts'})
    if hasattr(store, 'db'):
        from sqlalchemy import inspect

        from ..db.orm_models import Base

        existing = set(inspect(store.db.connection()).get_table_names())
        tables = [table for name, table in Base.metadata.tables.items()
                  if name in existing and (name.startswith(prefixes) or name in payment_evidence)]
        present = any(store.db.scalar(select(1).select_from(table).limit(1)) is not None for table in tables)
    else:
        families = store.__dict__.get('_integration_connections', {})
        present = any(rows for name, rows in families.items() if name.startswith(prefixes) or name in payment_evidence)
    if present:
        raise SnapshotError(['Dieser Bestand enthält geschützte Schnittstellen-, Kommunikations- oder Dokumentnachweise. '
                             'Bitte die vollständige Sicherung mit Datenbank, Originaldateien und Schlüsselring verwenden; '
                             'ein JSON-Teilbestand kann diese Quellen nicht verlustfrei sichern oder ersetzen.'])

def _tax_snapshot_guard(store):
    from .annual_tax_storage import guard_destructive_reset

    try:
        guard_destructive_reset(store)
    except ValueError:
        raise SnapshotError(["Gesicherte Steuerprofile und Exportoriginale benötigen das Vollbackup mit Schlüsseldatei. "
                             "Ein JSON-Teilbestand kann diese Belege nicht vollständig sichern oder ersetzen."]) from None


@dataclass(frozen=True)
class EntitySpec:
    key: str
    model: type[BaseModel]
    table: Table

    @property
    def references(self) -> list[tuple[str, str]]:
        """(column, referenced table) for every foreign key of the table."""
        return [(col.name, fk.column.table.name) for col in self.table.columns for fk in col.foreign_keys]

    @property
    def unique_columns(self) -> set[tuple[str, ...]]:
        unique = {
            tuple(col.name for col in constraint.columns)
            for constraint in self.table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        unique.update((col.name,) for col in self.table.columns if col.unique)
        return unique


@lru_cache(maxsize=1)
def entity_specs() -> tuple[EntitySpec, ...]:
    """Business entities in dependency order (parents before children)."""
    hints = typing.get_type_hints(InMemoryStore)
    specs = []
    for table in Base.metadata.sorted_tables:
        hint = hints.get(table.name)
        if hint is None:  # users, sessions and the audit log are not business data
            continue
        specs.append(EntitySpec(table.name, typing.get_args(hint)[1], table))
    return tuple(specs)


# Records are instances of the entity models; they share no base type with `id`.
Record = Any
Plan = list[tuple[EntitySpec, list[Record]]]


class _MemoryBackend:
    def __init__(self, store: InMemoryStore):
        self._store = store

    def records(self, spec: EntitySpec) -> list[Record]:
        return list(getattr(self._store, spec.key).values())

    def apply(self, plan: Plan, *, replace: bool, fresh_originals: list | None = None) -> None:
        from .document_versions import memory_archive
        with memory_archive(self._store).lock:
            self._apply(plan, replace=replace, fresh_originals=fresh_originals)

    def _apply(self, plan: Plan, *, replace: bool, fresh_originals: list | None = None) -> None:
        if replace:
            _require_full_bank_backup(self._store)
            _tax_snapshot_guard(self._store)
        # Stage complete collections first so a failure leaves the data untouched.
        staged = {}
        for spec, objs in plan:
            collection = {} if replace else dict(getattr(self._store, spec.key))
            collection.update((obj.id, obj) for obj in objs)
            staged[spec.key] = collection
        for key, collection in staged.items():
            target = getattr(self._store, key)
            target.clear()
            target.update(collection)
        originals.write_memory(self._store, fresh_originals or [])


class _SQLBackend:
    def __init__(self, session: Any):
        self._session = session

    def records(self, spec: EntitySpec) -> list[Record]:
        rows = self._session.execute(select(spec.table)).mappings()
        return [spec.model.model_validate(dict(row)) for row in rows]

    def apply(self, plan: Plan, *, replace: bool, fresh_originals: list | None = None) -> None:
        session = self._session
        try:
            if replace:
                from .document_versions import begin_writer
                begin_writer(session)
                _require_full_bank_backup(SimpleNamespace(db=session))
                _tax_snapshot_guard(SimpleNamespace(db=session))
                for spec, _ in reversed(plan):
                    session.execute(spec.table.delete())
            for spec, objs in plan:
                columns = set(spec.table.columns.keys())
                rows = [{k: v for k, v in obj.model_dump().items() if k in columns} for obj in objs]
                if rows:
                    session.execute(spec.table.insert(), rows)
            originals.write_sql(session, fresh_originals or [])
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.expunge_all()


def _backend(store: Any) -> _MemoryBackend | _SQLBackend:
    if isinstance(store, InMemoryStore):
        return _MemoryBackend(store)
    return _SQLBackend(store.db)


def export_snapshot(store: Any) -> dict:
    """All business data as a JSON-serialisable snapshot."""
    _require_full_bank_backup(store)

    _tax_snapshot_guard(store)
    backend = _backend(store)
    data: dict[str, Any] = {
        "format": SNAPSHOT_FORMAT,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "version": settings.app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    for spec in entity_specs():
        data[spec.key] = [obj.model_dump(mode="json") for obj in backend.records(spec)]
    data[originals.SNAPSHOT_KEY] = originals.export(store)
    return data


@dataclass
class PreparedImport:
    """A validated snapshot, ready to be written."""

    backend: _MemoryBackend | _SQLBackend
    plan: Plan
    replace: bool
    skipped: dict[str, int] = field(default_factory=dict)
    fresh_originals: list = field(default_factory=list)

    def apply(self) -> dict:
        self.backend.apply(self.plan, replace=self.replace, fresh_originals=self.fresh_originals)
        imported = {spec.key: len(objs) for spec, objs in self.plan if objs}
        if self.fresh_originals:
            imported[originals.SNAPSHOT_KEY] = len(self.fresh_originals)
        return {
            "imported": imported,
            "skipped_existing": self.skipped,
            "replace_existing": self.replace,
        }


def prepare_import(store: Any, data: Any, *, replace: bool) -> PreparedImport:
    """Validate a snapshot against the store; raises SnapshotError without writing."""
    if replace:
        _require_full_bank_backup(store)

        _tax_snapshot_guard(store)
    if not isinstance(data, dict):
        raise SnapshotError(["Die Datei enthält kein JSON-Objekt"])
    if "format" in data and data["format"] != SNAPSHOT_FORMAT:
        raise SnapshotError([f"Die Datei stammt nicht aus ImmoManager Pro (Format „{data['format']}“)"])
    version = data.get("format_version")
    if isinstance(version, int) and version > SNAPSHOT_FORMAT_VERSION:
        raise SnapshotError([f"Die Datei stammt aus einer neueren Version (Format {version}); bitte zuerst "
                             "ImmoManager Pro aktualisieren"])
    known = {spec.key for spec in entity_specs()} | {a for aliases in _KEY_ALIASES.values() for a in aliases}
    known.add(originals.SNAPSHOT_KEY)
    if not replace and not known & set(data):
        # merging nothing would report success for a file that holds no ImmoManager data at all
        raise SnapshotError(["Die Datei enthält keine ImmoManager-Daten"])
    if replace and data.get("format") != SNAPSHOT_FORMAT:
        raise SnapshotError([
            "Die Datei stammt aus einer älteren Version und ist unvollständig "
            "(u. a. ohne Abrechnungen und Zähler); eine Wiederherstellung würde Daten löschen. "
            "Bitte stattdessen importieren"
        ])

    if replace and originals.has_originals(store):
        raise SnapshotError([originals.RESTORE_REFUSED])

    specs = entity_specs()
    backend = _backend(store)
    parsed, problems = _parse(data, specs)
    incoming, original_problems = originals.parse(data.get(originals.SNAPSHOT_KEY))
    problems += original_problems
    existing: dict[str, dict[str, Record]] = {}
    if not replace:
        existing = {spec.key: {obj.id: obj for obj in backend.records(spec)} for spec in specs}

    plan: Plan = []
    skipped: dict[str, int] = {}
    for spec in specs:
        objs = parsed[spec.key]
        if not replace:
            fresh = [obj for obj in objs if obj.id not in existing[spec.key]]
            if len(fresh) != len(objs):
                skipped[spec.key] = len(objs) - len(fresh)
            objs = fresh
        plan.append((spec, _parents_first(spec, objs)))

    problems += _check_references(plan, existing)
    problems += _check_unique(plan, existing)
    problems += _check_final_statements(plan, existing)
    from .receivable_residuals import snapshot_problems as finance_snapshot_problems
    problems += finance_snapshot_problems(plan, existing)
    fresh_originals: list = []
    if incoming:
        after = {spec.key: {**existing.get(spec.key, {}), **{obj.id: obj for obj in objs}} for spec, objs in plan}
        fresh_originals, skipped_originals, original_problems = originals.check(store, incoming, after)
        problems += original_problems
        if skipped_originals:
            skipped[originals.SNAPSHOT_KEY] = skipped_originals
    if problems:
        raise SnapshotError(problems)
    return PreparedImport(backend, plan, replace, skipped, fresh_originals)


def import_snapshot(store: Any, data: Any, *, replace: bool) -> dict:
    return prepare_import(store, data, replace=replace).apply()


def clear_business_data(store: Any) -> None:
    empty = {"format": SNAPSHOT_FORMAT, "format_version": SNAPSHOT_FORMAT_VERSION}
    import_snapshot(store, empty, replace=True)


def _parse(data: dict, specs: tuple[EntitySpec, ...]) -> tuple[dict[str, list[Record]], list[str]]:
    parsed: dict[str, list[Record]] = {}
    problems: list[str] = []
    for spec in specs:
        raw = data.get(spec.key)
        if raw is None:
            raw = next((data[alias] for alias in _KEY_ALIASES.get(spec.key, ()) if alias in data), [])
        parsed[spec.key] = []
        if not isinstance(raw, list):
            problems.append(f"{spec.key}: Liste erwartet")
            continue
        seen: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                problems.append(f"{spec.key}[{index}]: Objekt erwartet")
                continue
            if not item.get("id"):
                item = {**item, "id": str(uuid4())}
            try:
                obj: Record = spec.model.model_validate(item)
            except PydanticValidationError as exc:
                error = exc.errors()[0]
                location = ".".join(str(part) for part in error["loc"])
                problems.append(f"{spec.key}[{index}] {location}: {error['msg']}")
                continue
            if obj.id in seen:
                problems.append(f"{spec.key}: ID {obj.id} kommt mehrfach vor")
                continue
            seen.add(obj.id)
            parsed[spec.key].append(obj)
    return parsed, problems


def _parents_first(spec: EntitySpec, objs: list[Record]) -> list[Record]:
    """Order rows of a self-referencing table (e.g. sub-tasks) parents first."""
    self_refs = [column for column, target in spec.references if target == spec.key]
    if not self_refs or len(objs) < 2:
        return objs
    ids = {obj.id for obj in objs}
    ordered: list[Record] = []
    placed: set[str] = set()
    pending = objs
    while pending:
        waiting = []
        for obj in pending:
            parents = {getattr(obj, column, None) for column in self_refs} & ids
            if parents - placed - {obj.id}:
                waiting.append(obj)
            else:
                ordered.append(obj)
                placed.add(obj.id)
        if len(waiting) == len(pending):  # cycle: leave it to the database to reject
            ordered.extend(waiting)
            break
        pending = waiting
    return ordered


def _check_references(plan: Plan, existing: dict[str, dict[str, Record]]) -> list[str]:
    known = {spec.key: {obj.id for obj in objs} | set(existing.get(spec.key, {})) for spec, objs in plan}
    problems = []
    for spec, objs in plan:
        for column, target in spec.references:
            if target not in known:
                continue
            for obj in objs:
                value = getattr(obj, column, None)
                if value and value not in known[target]:
                    problems.append(
                        f"{spec.key} {obj.id}: {column} verweist auf fehlenden Datensatz {value}"
                    )
    return problems


def _check_final_statements(plan: Plan, existing: dict[str, dict[str, Record]]) -> list[str]:
    """Issued statements stay as issued: neither edited in the file nor extended by a merge."""
    incoming = {spec.key: objs for spec, objs in plan}
    problems = []
    existing_periods = existing.get("billing_periods", {})
    for key in ("utility_statements", "cost_items"):
        for obj in incoming.get(key, []):
            period = existing_periods.get(obj.billing_period_id)
            if period is not None and period.status in FINAL_STATUSES:
                problems.append(f"{key} {obj.id}: Abrechnungsperiode {period.label} ist finalisiert und "
                                "bleibt unverändert")
    # only the periods this file brings or adds to; existing data is not judged here
    touched = {p.id for p in incoming.get("billing_periods", [])}
    touched |= {s.billing_period_id for s in incoming.get("utility_statements", [])}
    periods = {**existing_periods, **{p.id: p for p in incoming.get("billing_periods", [])}}
    statements: dict[str, list[Record]] = {}
    for statement in [*existing.get("utility_statements", {}).values(), *incoming.get("utility_statements", [])]:
        statements.setdefault(statement.billing_period_id, []).append(statement)
    for period_id in sorted(touched):
        if period_id in periods:
            problems += final_version_problems(periods[period_id], statements.get(period_id, []))
    return problems


def _check_unique(plan: Plan, existing: dict[str, dict[str, Record]]) -> list[str]:
    problems = []
    for spec, objs in plan:
        for columns in sorted(spec.unique_columns):
            owners: dict[tuple, str] = {}
            for obj in [*existing.get(spec.key, {}).values(), *objs]:
                value = tuple(getattr(obj, column, None) for column in columns)
                if any(part is None for part in value):
                    continue
                owner = owners.setdefault(value, obj.id)
                if owner != obj.id:
                    shown = ", ".join(str(part) for part in value)
                    problems.append(f"{spec.key} {obj.id}: {', '.join(columns)} „{shown}“ ist bereits vergeben")
    return problems
