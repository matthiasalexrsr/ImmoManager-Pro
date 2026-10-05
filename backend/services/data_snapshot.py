"""Lossless JSON snapshots of the business data: export, import and restore.

The entity list is derived from the database schema (every business table the
in-memory store mirrors), so new tables are covered without touching this
module. Records keep their IDs, which keeps every reference between them
intact, and a snapshot is validated completely before anything is written:

* merge (import): records whose ID already exists are skipped, so importing
  the same file twice changes nothing;
* replace (restore): the business data is swapped all or nothing.

User accounts, sessions and the audit log are not part of a snapshot.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Table, UniqueConstraint, select

from ..config import settings
from ..db.orm_models import Base
from ..storage import InMemoryStore

SNAPSHOT_FORMAT = "immomanager-snapshot"
SNAPSHOT_FORMAT_VERSION = 2

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

    def apply(self, plan: Plan, *, replace: bool) -> None:
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


class _SQLBackend:
    def __init__(self, session: Any):
        self._session = session

    def records(self, spec: EntitySpec) -> list[Record]:
        rows = self._session.execute(select(spec.table)).mappings()
        return [spec.model.model_validate(dict(row)) for row in rows]

    def apply(self, plan: Plan, *, replace: bool) -> None:
        session = self._session
        try:
            if replace:
                for spec, _ in reversed(plan):
                    session.execute(spec.table.delete())
            for spec, objs in plan:
                columns = set(spec.table.columns.keys())
                rows = [{k: v for k, v in obj.model_dump().items() if k in columns} for obj in objs]
                if rows:
                    session.execute(spec.table.insert(), rows)
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
    backend = _backend(store)
    data: dict[str, Any] = {
        "format": SNAPSHOT_FORMAT,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "version": settings.app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    for spec in entity_specs():
        data[spec.key] = [obj.model_dump(mode="json") for obj in backend.records(spec)]
    return data


@dataclass
class PreparedImport:
    """A validated snapshot, ready to be written."""

    backend: _MemoryBackend | _SQLBackend
    plan: Plan
    replace: bool
    skipped: dict[str, int] = field(default_factory=dict)

    def apply(self) -> dict:
        self.backend.apply(self.plan, replace=self.replace)
        return {
            "imported": {spec.key: len(objs) for spec, objs in self.plan if objs},
            "skipped_existing": self.skipped,
            "replace_existing": self.replace,
        }


def prepare_import(store: Any, data: Any, *, replace: bool) -> PreparedImport:
    """Validate a snapshot against the store; raises SnapshotError without writing."""
    if not isinstance(data, dict):
        raise SnapshotError(["Die Datei enthält kein JSON-Objekt"])
    if "format" in data and data["format"] != SNAPSHOT_FORMAT:
        raise SnapshotError([f"Die Datei stammt nicht aus ImmoManager Pro (Format „{data['format']}“)"])
    version = data.get("format_version")
    if isinstance(version, int) and version > SNAPSHOT_FORMAT_VERSION:
        raise SnapshotError([f"Die Datei stammt aus einer neueren Version (Format {version}); bitte zuerst "
                             "ImmoManager Pro aktualisieren"])
    known = {spec.key for spec in entity_specs()} | {a for aliases in _KEY_ALIASES.values() for a in aliases}
    if not replace and not known & set(data):
        # merging nothing would report success for a file that holds no ImmoManager data at all
        raise SnapshotError(["Die Datei enthält keine ImmoManager-Daten"])
    if replace and data.get("format") != SNAPSHOT_FORMAT:
        raise SnapshotError([
            "Die Datei stammt aus einer älteren Version und ist unvollständig "
            "(u. a. ohne Abrechnungen und Zähler); eine Wiederherstellung würde Daten löschen. "
            "Bitte stattdessen importieren"
        ])

    specs = entity_specs()
    backend = _backend(store)
    parsed, problems = _parse(data, specs)
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
    if problems:
        raise SnapshotError(problems)
    return PreparedImport(backend, plan, replace, skipped)


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
