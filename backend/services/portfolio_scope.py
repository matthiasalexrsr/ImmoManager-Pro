"""Authoritative request scopes, shared by ORM and explicit Core/streaming queries.

No actor means an installation-internal operation (setup, scheduled work, backup).
Every authenticated HTTP request installs an actor read freshly from the server.
Roles grant actions; the independent portfolio boundary grants resource access.
"""

from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, and_, event, exists, false, func, literal, or_, select, true
from sqlalchemy import cast as sql_cast
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.selectable import Alias, Join
from sqlalchemy.sql.util import ClauseAdapter

from ..db.access_models import ResourcePortfolioORM, UploadAccessORM, UserAccessORM, UserPortfolioORM
from ..db.orm_models import Base
from .portfolio_references import CSVReferencesVisible, csv_parents, reference_ids


def ensure_portfolio_access_schema(connection, *, bootstrap_legacy=False):
    """Startup compatibility for historical create_all databases, before auth.

    Only the explicit first compatibility upgrade may set bootstrap_legacy=True,
    after detecting that the access table was absent before schema creation.
    Ordinary startup never fills missing access rows or widens grants.
    """
    for model in (UserAccessORM, UserPortfolioORM, ResourcePortfolioORM, UploadAccessORM):
        table: Any = model.__table__
        table.create(connection, checkfirst=True)
    if not bootstrap_legacy:
        return
    table = UserAccessORM.__table__
    insert_factory: Any
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert_factory = sqlite_insert
    elif connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        insert_factory = pg_insert
    else:
        raise RuntimeError("Portfoliozugriff unterstützt SQLite und PostgreSQL")
    users = Base.metadata.tables["users"]
    statement = (
        insert_factory(table)
        .from_select(
            ["user_id", "mode", "origin", "updated_at"],
            select(users.c.id, literal("all"), literal("legacy_all"), func.current_timestamp()).where(true()),
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    connection.execute(statement)


@dataclass(frozen=True)
class AccessScope:
    user_id: str
    role: str
    unrestricted: bool
    portfolio_ids: tuple[str, ...] = ()


_scope: ContextVar[AccessScope | None] = ContextVar("immo_portfolio_scope", default=None)
_guarding: ContextVar[bool] = ContextVar("immo_scope_guarding", default=False)
GLOBAL_READ = frozenset({"tax_rates", "notification_templates", "escalation_rules"})
INTERNAL = frozenset(
    {
        "users",
        "auth_setup",
        "auth_sessions",
        "auth_refresh_tokens",
        "user_preferences",
        "form_drafts",  # Each operation explicitly binds the freshly checked actor.
        "login_attempts",
        "revoked_tokens",
        "audit_logs",
        "user_portfolio_access",
        "user_portfolio_grants",
        "resource_portfolio_grants",
        "upload_portfolio_grants",
        "operational_lock",
        "operational_ticks",
        "operational_occurrences",
        "operational_schedules",
        "operational_dispatches",
        "operational_jobs",  # Bound installation actor is checked in the job service.
        "operational_job_lanes",
        "operational_work_items",
    }
)
RESOURCE_ALIASES = {
    "portfolio": "portfolios",
    "property": "properties",
    "unit": "units",
    "tenant": "tenants",
    "account": "accounts",
    "category": "categories",
    "contract": "contracts",
    "booking": "bookings",
    "receivable": "receivables",
    "rent_charge": "rent_charges",
    "invoice": "invoices",
    "document": "documents",
    "task": "tasks",
    "calendar": "calendar_events",
    "maintenance": "maintenance_cases",
    "maintenance_case": "maintenance_cases",
    "listing": "listings",
    "lead": "leads",
    "contact": "contacts",
    "billing_period": "billing_periods",
    "utility_statement": "utility_statements",
    "meter": "meters",
    "viewing": "viewing_appointments",
    "handover_protocol": "handover_protocols",
    "deposit": "deposits",
    "rent_adjustment": "rent_adjustments",
    "meter_reading": "meter_readings",
    "tax_rate": "tax_rates",
    "budget": "budgets",
    "escalation_rule": "escalation_rules",
    "insurance": "insurances",
    "standalone_reading": "standalone_meter_readings",
    "allocation_key": "allocation_keys",
    "cost_item": "cost_items",
    "entity_photo": "entity_photos",
    "notification": "notifications",
    "notification_template": "notification_templates",
    "message_thread": "message_threads",
    "message": "messages",
    "listing_photo": "listing_photos",
}
TEXT_PARENTS = {
    "contract_id": "contracts",
    "property_id": "properties",
    "unit_id": "units",
    "tenant_id": "tenants",
    "statement_id": "utility_statements",
    "source_document_id": "documents",
}


def current_scope() -> AccessScope | None:
    return _scope.get()


@contextmanager
def scope_context(scope: AccessScope | None) -> Iterator[None]:
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)


def scope_from_user(user: dict) -> AccessScope:
    return AccessScope(
        user["id"],
        user["role"],
        user["role"] == "eigentuemer" or user.get("portfolio_access", "all") == "all",
        tuple(sorted(user.get("portfolio_ids", []))),
    )


def refresh_scope(captured: AccessScope | None) -> AccessScope | None:
    """A stream terminates if grants change, rather than succeeding with a partial CSV."""
    if captured is None:
        return None
    from ..auth import get_user_by_id

    user = get_user_by_id(captured.user_id)
    if not user or not user["is_active"] or scope_from_user(user) != captured:
        raise HTTPException(403, "Berechtigungen wurden geändert. Bitte die Anfrage erneut starten.")
    return captured


def _parents(table):
    result = {}
    for column in table.c:
        foreign = next(iter(column.foreign_keys), None)
        parent = foreign.target_fullname.split(".")[0] if foreign else TEXT_PARENTS.get(column.name)
        if parent in Base.metadata.tables and parent not in INTERNAL and parent != table.name:
            # Tenant visibility derives from contracts; including this edge in
            # contract visibility would introduce a cycle. Writes still check it.
            if table.name == "contracts" and parent == "tenants":
                continue
            result[column.name] = parent
    return result


def _binding(table, scope):
    grants = ResourcePortfolioORM.__table__
    return exists(
        select(1).where(
            grants.c.resource_type == table.name,
            grants.c.resource_id == sql_cast(table.c.id, String),
            grants.c.portfolio_id.in_(scope.portfolio_ids),
        )
    ).correlate(table)


def _reachable_scope_tables(table, relations):
    key = ("reachable", table.name)
    if key not in relations:
        pending, reachable = [table.name], set()
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            current = Base.metadata.tables[name]
            if name in INTERNAL or name in GLOBAL_READ or name == "portfolios" or "portfolio_id" in current.c:
                continue
            if name == "tenants":
                pending.append("contracts")
                continue
            pending.extend(_parents(current).values())
            pending.extend(csv_parents(current).values())
            if "entity_type" in current.c and "entity_id" in current.c:
                pending.extend(parent for parent in RESOURCE_ALIASES.values()
                               if parent != name and parent in Base.metadata.tables)
        relations[key] = frozenset(reachable)
    return relations[key]


def _visible_ids(table, scope, seen, relations):
    """Factor parent predicates into statement-local, reusable SQL relations.

    Expanding every polymorphic parent inside every descendant creates deeply
    nested SQL that exceeds the parser stack of supported SQLite versions.
    Ordinary CTEs preserve the same snapshot and exact parent identity without
    collecting resource IDs in application memory or changing cycle denial.
    """
    # Ancestors this parent cannot reach do not affect its cycle predicate.
    # Canonicalising only those names shares leaf relations across all branches.
    relevant_seen = frozenset(seen) & _reachable_scope_tables(table, relations)
    key = (table.name, relevant_seen)
    if key not in relations:
        criterion = _criterion(table, scope, tuple(sorted(relevant_seen)), relations)
        relations[key] = select(table.c.id).where(criterion).correlate(None).cte()
    return relations[key]


def _criterion(table, scope, seen=(), relations=None):
    relations = {} if relations is None else relations
    name = table.name
    if name in INTERNAL:
        return None
    if name in GLOBAL_READ:
        return true()
    if name in seen:
        return false()
    if name == "portfolios":
        return table.c.id.in_(scope.portfolio_ids)
    if "portfolio_id" in table.c:
        return table.c.portfolio_id.in_(scope.portfolio_ids)
    if name == "tenants":
        contracts = Base.metadata.tables["contracts"]
        visible_contracts = _visible_ids(contracts, scope, (*seen, name), relations)
        linked = exists(
            select(1).where(contracts.c.tenant_id == table.c.id, contracts.c.id.in_(select(visible_contracts.c.id)))
        ).correlate(table)
        return or_(linked, _binding(table, scope))
    clauses, anchors = [], []
    for field, parent_name in _parents(table).items():
        parent = Base.metadata.tables[parent_name]
        allowed_parent = _visible_ids(parent, scope, (*seen, name), relations)
        visible = exists(
            select(1).where(allowed_parent.c.id == table.c[field])
        ).correlate(table)
        clauses.append(or_(table.c[field].is_(None), visible))
        anchors.append(table.c[field].is_not(None))
    for field, parent_name in csv_parents(table).items():
        parent = Base.metadata.tables[parent_name]
        allowed_parent = _visible_ids(parent, scope, (*seen, name), relations)
        clauses.append(CSVReferencesVisible(table.c[field], allowed_parent, true()))
        anchors.append(and_(table.c[field].is_not(None), table.c[field] != ""))
    if "entity_type" in table.c and "entity_id" in table.c:
        options = []
        for entity_type, parent_name in RESOURCE_ALIASES.items():
            if parent_name == name:
                continue
            entity_parent = Base.metadata.tables.get(parent_name or "")
            if entity_parent is not None:
                allowed_parent = _visible_ids(entity_parent, scope, (*seen, name), relations)
                options.append(
                    and_(
                        table.c.entity_type == entity_type,
                        exists(
                            select(1).where(
                                allowed_parent.c.id == table.c.entity_id
                            )
                        ).correlate(table),
                    )
                )
        reference = or_(*options) if options else false()
        clauses.append(or_(table.c.entity_id.is_(None), reference))
        anchors.append(table.c.entity_id.is_not(None))
    # Unlinked historical records belong to the installation. Explicitly
    # assigned/created unlinked records are visible only to their portfolios.
    return and_(*clauses, or_(*anchors, _binding(table, scope)))


def scoped_clause(model_or_table, *, scope=None):
    scope = current_scope() if scope is None else scope
    if scope is None or scope.unrestricted:
        return None
    table = getattr(model_or_table, "__table__", model_or_table)
    return _criterion(table, scope)


def require_installation_scope():
    scope = current_scope()
    if scope is not None and not scope.unrestricted:
        raise HTTPException(
            403, "Diese Aktion verwaltet installationsweite Daten und benötigt Zugriff auf alle Portfolios."
        )


def require_assigned_scope():
    scope = current_scope()
    if scope is not None and not scope.unrestricted and not scope.portfolio_ids:
        raise HTTPException(403, "Bitte zuerst ein Portfolio zuweisen lassen.")


def resource_visible(entity_type, entity_id):
    """Bounded, authoritative checks for cached search hits; cache is not a grant."""
    scope = current_scope()
    if scope is None or scope.unrestricted:
        return True
    from ..dependencies import store

    name = RESOURCE_ALIASES.get(entity_type)
    table = Base.metadata.tables.get(name or "")
    if table is None:
        return False
    if hasattr(store, "db"):
        return _sql_visible(store.db, table, entity_id)
    item = object.__getattribute__(store, "__dict__").get(name, {}).get(entity_id)
    return item is not None and memory_visible(store, name, item)


def _core_sources(source, nullable=False):
    if isinstance(source, Join):
        yield from _core_sources(source.left, nullable or source.full)
        yield from _core_sources(source.right, nullable or source.isouter or source.full)
    else:
        yield source, nullable


@event.listens_for(Session, "do_orm_execute")
def _scope_queries(state):
    scope = current_scope()
    if scope is None or scope.unrestricted or _guarding.get():
        return
    statement = state.statement
    if state.is_orm_statement:
        for mapper in state.all_mappers:
            criterion = scoped_clause(mapper.class_, scope=scope)
            if criterion is not None:
                statement = statement.options(with_loader_criteria(mapper.class_, criterion, include_aliases=True))
    elif state.is_select:
        # Session.execute(Core SELECT) is used by coherent privacy/finance
        # snapshots. Independent Engine connections use scoped_clause explicitly.
        for source in statement.get_final_froms():
            for table, nullable in _core_sources(source):
                original = table.original if isinstance(table, Alias) else table
                if getattr(original, "name", None) not in Base.metadata.tables:
                    continue
                criterion = scoped_clause(Base.metadata.tables[getattr(original, "name")], scope=scope)
                if criterion is not None and table is not original:
                    criterion = ClauseAdapter(table).traverse(criterion)
                if criterion is not None:
                    if nullable and "id" in table.c:
                        criterion = or_(table.c.id.is_(None), criterion)
                    statement = statement.where(criterion)
    if state.is_update or state.is_delete:
        table = statement.table
        criterion = scoped_clause(table, scope=scope)
        if criterion is not None:
            statement = statement.where(criterion)
        if state.is_update:
            updates = {}
            for key, value in (getattr(statement, "_values", None) or {}).items():
                field = getattr(key, "key", key)
                column = table.c.get(field)
                if column is not None and (
                    column.foreign_keys
                    or field in TEXT_PARENTS
                    or field in csv_parents(table)
                    or field in {"entity_id", "entity_type", "file_url", "photo_url"}
                ):
                    if not isinstance(value, BindParameter):
                        raise HTTPException(403, "Referenzen dürfen nur mit explizit geprüften Werten geändert werden.")
                updates[field] = getattr(value, "value", None)
            guard_sql_write(state.session, table, updates)
    state.statement = statement
    if state.is_update or state.is_delete:
        connection = state.session.connection(bind_arguments=state.bind_arguments)
        if connection.dialect.name == "sqlite":
            # sqlite3's legacy transaction detection does not recognise leading
            # WITH as DML. A SQLAlchemy logical transaction alone would allow
            # scoped CTE writes to autocommit and survive a later rollback.
            if not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            result = state.invoke_statement()
            # The same sqlite3 detection reports -1 for WITH ... UPDATE/DELETE.
            # Read the connection-local count before any subsequent statement;
            # keep the original result and every existing CAS/lock contract.
            # RETURNING remains untouched, and changes() is not an aggregate
            # count for executemany.
            if (isinstance(result, CursorResult) and not state.is_executemany
                    and not result.returns_rows and result.rowcount == -1):
                result.rowcount = connection.exec_driver_sql("SELECT changes()").scalar_one()
            return result


def _sql_visible(db, table, entity_id):
    criterion = scoped_clause(table)
    query = select(table.c.id).where(table.c.id == entity_id)
    if criterion is not None:
        query = query.where(criterion)
    return db.scalar(query) is not None


def guard_sql_write(db, table, values, *, entity_id=None, creating=False):
    scope = current_scope()
    if scope is None or scope.unrestricted or table.name in INTERNAL:
        return
    if not scope.portfolio_ids:
        raise HTTPException(403, "Bitte zuerst ein Portfolio zuweisen lassen.")
    if table.name in GLOBAL_READ or (table.name == "portfolios" and creating):
        require_installation_scope()
    if entity_id is not None and not _sql_visible(db, table, entity_id):
        raise HTTPException(404, "Datensatz nicht gefunden")
    if entity_id is not None and table.name == "tenants":
        contracts = Base.metadata.tables["contracts"]
        token = _guarding.set(True)
        try:
            shared = db.scalar(
                select(contracts.c.id).where(contracts.c.tenant_id == entity_id, ~scoped_clause(contracts)).limit(1)
            )
        finally:
            _guarding.reset(token)
        if shared:
            raise HTTPException(
                403, "Ein gemeinsam genutztes Mieterprofil benötigt Zugriff auf alle zugehörigen Portfolios."
            )
    for field, value in values.items():
        column = table.c.get(field)
        if column is None or value is None:
            continue
        foreign = next(iter(column.foreign_keys), None)
        parent_name = foreign.target_fullname.split(".")[0] if foreign else TEXT_PARENTS.get(field)
        parent = Base.metadata.tables.get(parent_name or "")
        if parent is not None and parent_name not in INTERNAL and not _sql_visible(db, parent, value):
            raise HTTPException(403, "Die Referenz liegt außerhalb Ihrer erlaubten Portfolios.")
    for field, parent_name in csv_parents(table).items():
        for identifier in reference_ids(values.get(field)):
            if not _sql_visible(db, Base.metadata.tables[parent_name], identifier):
                raise HTTPException(403, "Die Referenz liegt außerhalb Ihrer erlaubten Portfolios.")
    if values.get("entity_id") is not None:
        parent_name = RESOURCE_ALIASES.get(values.get("entity_type"))
        parent = Base.metadata.tables.get(parent_name or "")
        if parent is None or not _sql_visible(db, parent, values["entity_id"]):
            raise HTTPException(403, "Die Referenz liegt außerhalb Ihrer erlaubten Portfolios.")
    for field in ("file_url", "photo_url"):
        if values.get(field):
            require_file_access(values[field])


@event.listens_for(Session, "before_flush")
def _scope_native_writes(db, context, instances):
    scope = current_scope()
    if scope is None or scope.unrestricted or _guarding.get():
        return
    for item in list(db.new) + list(db.dirty) + list(db.deleted):
        table = item.__table__
        if table.name in INTERNAL:
            continue
        values = {column.name: getattr(item, column.name) for column in table.c}
        new = item in db.new
        if new and "id" in table.c and item.id is None:
            from uuid import uuid4

            item.id = str(uuid4())
            values["id"] = item.id
        guard_sql_write(db, table, values, entity_id=None if new else item.id, creating=new)
        if new and "id" in table.c and item.id and table.name not in GLOBAL_READ:
            # Only unanchored records need explicit membership. Keep this in
            # the same transaction as the insert; a failure rolls both back.
            if not any(values.get(field) for field in _parents(table)) and not values.get("entity_id"):
                db.add_all(
                    ResourcePortfolioORM(resource_type=table.name, resource_id=item.id, portfolio_id=pid)
                    for pid in scope.portfolio_ids
                )


def require_file_access(value: str):
    scope = current_scope()
    if scope is None or scope.unrestricted:
        return
    from ..dependencies import store
    from ..routers.files import _file_url_to_key, _ocr_key_from_file_key

    key = _file_url_to_key(value)
    candidates = {key}
    # An OCR sidecar inherits exactly the source file's access.
    if key.endswith("_ocr.txt"):
        stem = key[:-8]
        for extension in ("pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"):
            candidates.add(stem + "." + extension)
    if hasattr(store, "db"):
        linked = False
        for name, field in (
            ("documents", "file_url"),
            ("entity_photos", "file_url"),
            ("listing_photos", "file_url"),
            ("meter_readings", "photo_url"),
            ("standalone_meter_readings", "photo_url"),
        ):
            table = Base.metadata.tables[name]
            matches = or_(
                *(
                    or_(
                        table.c[field] == k,
                        table.c[field] == "uploads/" + k,
                        table.c[field].endswith("/" + k, autoescape=True),
                    )
                    for k in candidates
                )
            )
            if store.db.scalar(select(table.c.id).where(matches, scoped_clause(table, scope=scope)).limit(1)):
                return
            token = _guarding.set(True)
            try:
                linked = linked or store.db.scalar(select(table.c.id).where(matches).limit(1)) is not None
            finally:
                _guarding.reset(token)
        # Upload ownership covers only unlinked drafts. Once a document/photo
        # is attached, its current resource scope governs the bytes as well.
        grants = UploadAccessORM.__table__
        if not linked and store.db.scalar(
            select(grants.c.storage_key)
            .where(grants.c.storage_key.in_(candidates), grants.c.portfolio_id.in_(scope.portfolio_ids))
            .limit(1)
        ):
            return
    else:
        raw = object.__getattribute__(store, "__dict__")
        linked = False
        for name, field in (
            ("documents", "file_url"),
            ("entity_photos", "file_url"),
            ("listing_photos", "file_url"),
            ("meter_readings", "photo_url"),
            ("standalone_meter_readings", "photo_url"),
        ):
            for item in getattr(store, name).values():
                file_key = _file_url_to_key(getattr(item, field, "") or "")
                if file_key in candidates or _ocr_key_from_file_key(file_key) == key:
                    return
            linked = linked or any(
                _file_url_to_key(getattr(item, field, "") or "") in candidates for item in raw[name].values()
            )
        if not linked and any(
            pid in scope.portfolio_ids for k, pid in raw.get("_upload_grants", ()) if k in candidates
        ):
            return
    raise HTTPException(404, "Datei nicht gefunden")


def register_upload(key: str):
    scope = current_scope()
    if scope is None or scope.unrestricted:
        return
    if not scope.portfolio_ids:
        raise HTTPException(403, "Bitte zuerst ein Portfolio zuweisen lassen.")
    from ..dependencies import store

    if hasattr(store, "db"):
        store.db.add_all(
            UploadAccessORM(storage_key=key, portfolio_id=pid, uploaded_by=scope.user_id) for pid in scope.portfolio_ids
        )
        store.db.commit()
    else:
        store.__dict__.setdefault("_upload_grants", set()).update((key, pid) for pid in scope.portfolio_ids)


COLLECTION_TABLES = {
    "viewing_appointments": "viewing_appointments",
    "standalone_meter_readings": "standalone_meter_readings",
}


def memory_visible(store, collection, item, *, scope=None, seen=()):
    scope = current_scope() if scope is None else scope
    if scope is None or scope.unrestricted:
        return True
    name = COLLECTION_TABLES.get(collection, collection)
    if name in GLOBAL_READ:
        return True
    if name in seen:
        return False
    raw = object.__getattribute__(store, "__dict__")
    if name == "portfolios":
        return item.id in scope.portfolio_ids
    if hasattr(item, "portfolio_id"):
        return item.portfolio_id in scope.portfolio_ids
    binding = any(
        pid in scope.portfolio_ids
        for kind, identifier, pid in raw.get("_resource_grants", ())
        if kind == name and identifier == item.id
    )
    if name == "tenants":
        return binding or any(
            contract.tenant_id == item.id
            and memory_visible(store, "contracts", contract, scope=scope, seen=(*seen, name))
            for contract in raw["contracts"].values()
        )
    table = Base.metadata.tables.get(name or "")
    if table is None:
        return False
    anchors = False
    parents = _parents(table)
    for field, parent_name in csv_parents(table).items():
        for identifier in reference_ids(getattr(item, field, None)):
            parent = raw.get(parent_name, {}).get(identifier)
            if parent is None or not memory_visible(store, parent_name, parent, scope=scope, seen=(*seen, name)):
                return False
            anchors = True
    # Memory receipts use the canonical entity_type/entity_id instead of two
    # nullable SQL target foreign keys. Other references share the SQL graph.
    for field, parent_name in parents.items():
        value = getattr(item, field, None)
        if value is None:
            continue
        parent = raw.get(parent_name, {}).get(value)
        if parent is None or not memory_visible(store, parent_name, parent, scope=scope, seen=(*seen, name)):
            return False
        anchors = True
    if getattr(item, "entity_id", None) is not None:
        parent_name = RESOURCE_ALIASES.get(item.entity_type)
        parent = raw.get(parent_name, {}).get(item.entity_id)
        if parent is None or not memory_visible(store, parent_name, parent, scope=scope, seen=(*seen, name)):
            return False
        anchors = True
    return anchors or binding


class ScopedCollection(MutableMapping):
    """Live views preserve the memory store's existing financial locks/guards."""

    def __init__(self, store, name, raw):
        self.store, self.name, self.raw = store, name, raw

    def __getitem__(self, key):
        item = self.raw[key]
        if not memory_visible(self.store, self.name, item):
            raise KeyError(key)
        return item

    def __iter__(self):
        return iter([key for key, item in self.raw.items() if memory_visible(self.store, self.name, item)])

    def __len__(self):
        return sum(1 for _ in self)

    def __setitem__(self, key, item):
        scope = current_scope()
        if scope is None or scope.unrestricted:
            self.raw[key] = item
            return
        if self.name in GLOBAL_READ or (self.name == "portfolios" and key not in self.raw):
            require_installation_scope()
        if not scope.portfolio_ids:
            raise HTTPException(403, "Bitte zuerst ein Portfolio zuweisen lassen.")
        if key in self.raw and not memory_visible(self.store, self.name, self.raw[key]):
            raise HTTPException(404, "Datensatz nicht gefunden")
        raw = object.__getattribute__(self.store, "__dict__")
        if (
            self.name == "tenants"
            and key in self.raw
            and any(
                contract.tenant_id == item.id and not memory_visible(self.store, "contracts", contract)
                for contract in raw["contracts"].values()
            )
        ):
            raise HTTPException(
                403, "Ein gemeinsam genutztes Mieterprofil benötigt Zugriff auf alle zugehörigen Portfolios."
            )
        table = Base.metadata.tables.get(self.name)
        if table is not None:
            for field, parent_name in csv_parents(table).items():
                for identifier in reference_ids(getattr(item, field, None)):
                    parent = raw.get(parent_name, {}).get(identifier)
                    if parent is None or not memory_visible(self.store, parent_name, parent):
                        raise HTTPException(403, "Die Referenz liegt außerhalb Ihrer erlaubten Portfolios.")
        for field in item.model_dump() if hasattr(item, "model_dump") else vars(item):
            value = getattr(item, field, None)
            column = table.c.get(field) if table is not None else None
            foreign = next(iter(column.foreign_keys), None) if column is not None else None
            parent_name = foreign.target_fullname.split(".")[0] if foreign else TEXT_PARENTS.get(field)
            if value is not None and parent_name and parent_name not in INTERNAL:
                parent = raw.get(parent_name, {}).get(value)
                if parent is None or not memory_visible(self.store, parent_name, parent):
                    raise HTTPException(403, "Die Referenz liegt außerhalb Ihrer erlaubten Portfolios.")
        if getattr(item, "entity_id", None) is not None:
            parent_name = RESOURCE_ALIASES.get(item.entity_type)
            parent = raw.get(parent_name, {}).get(item.entity_id)
            if parent is None or not memory_visible(self.store, parent_name, parent):
                raise HTTPException(403, "Die Referenz liegt außerhalb Ihrer erlaubten Portfolios.")
        for field in ("file_url", "photo_url"):
            if getattr(item, field, None):
                require_file_access(getattr(item, field))
        if not memory_visible(self.store, self.name, item):
            parents = _parents(table) if table is not None else {}
            if any(getattr(item, field, None) for field in parents) or getattr(item, "entity_id", None):
                raise HTTPException(403, "Die Referenz liegt außerhalb Ihrer erlaubten Portfolios.")
            raw.setdefault("_resource_grants", set()).update((self.name, key, pid) for pid in scope.portfolio_ids)
        self.raw[key] = item

    def __delitem__(self, key):
        self[key]
        if self.name in GLOBAL_READ:
            require_installation_scope()
        del self.raw[key]
