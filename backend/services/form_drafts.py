"""Private encrypted drafts with atomic tab conflicts and fresh resource grants.

Drafts never call a domain create/update/payment command. The saved original
business revision is retained even when that business row has since changed.
"""

import hashlib
import json
import math
import os
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Table, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from .. import auth, models
from ..config import settings
from ..db.form_draft_models import FormDraftORM
from ..db.orm_models import Base
from ..form_draft_models import DraftIdentity, DraftWrite
from ..permissions import may_write_resource
from . import form_draft_crypto
from .concurrency import COLLECTIONS, utc_datetime
from .iban_encryption import IBANEncryptionError
from .payments import _memory_lock
from .portfolio_references import csv_parents, reference_ids
from .portfolio_scope import (
    INTERNAL,
    TEXT_PARENTS,
    memory_visible,
    refresh_scope,
    require_file_access,
    scope_context,
)

# Explicit ordinary editors. Security, journal commands and finalized statements
# have no generic draft endpoint, even if they happen to use the same UI modal.
POLICIES = {
    "portfolios": "Portfolio", "properties": "Property", "units": "Unit", "tenants": "Tenant",
    "contracts": "Contract", "accounts": "Account", "categories": "Category", "bookings": "Booking",
    "receivables": "Receivable", "invoices": "Invoice", "maintenance": "MaintenanceCase", "documents": "Document",
    "tasks": "Task", "calendar": "CalendarEvent", "listings": "Listing", "leads": "Lead", "viewings": "ViewingAppointment",
    "deposits": "Deposit", "tax-rates": "TaxRate", "budgets": "Budget", "rent-adjustments": "RentAdjustment",
    "handover-protocols": "HandoverProtocol", "insurances": "Insurance", "contacts": "Contact", "meters": "Meter",
    "meters/readings": "StandaloneMeterReading", "notifications/templates": "NotificationTemplate",
    "messages/threads": "MessageThread", "escalation/rules": "EscalationRule", "billing/periods": "BillingPeriod",
    "billing/allocation-keys": "AllocationKey", "billing/cost-items": "CostItem",
}
FORBIDDEN_KEYS = {"password", "secret", "token", "access_token", "refresh_token", "file", "file_bytes", "signature"}


class DraftError(HTTPException):
    def __init__(self, status, code, message):
        self.code = code
        super().__init__(status, message)


def limits():
    """Optional installation settings; invalid values never silently fall back."""
    try:
        ttl = int(os.environ.get("FORM_DRAFT_TTL_DAYS", str(getattr(settings, "form_draft_ttl_days", 7))))
        budget = int(os.environ.get("FORM_DRAFT_MAX_BYTES", str(getattr(settings, "form_draft_max_bytes", 262144))))
        if not 1 <= ttl <= 365 or not 1024 <= budget <= 16 * 1024 * 1024:
            raise ValueError()
    except ValueError:
        raise DraftError(503, "DRAFT_CONFIGURATION_INVALID", "Entwurfsschutz ist nicht eingerichtet. FORM_DRAFT_TTL_DAYS (1–365) und FORM_DRAFT_MAX_BYTES (1024–16777216) korrigieren.") from None
    return ttl, budget


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def identity_key(identity, actor):
    return hashlib.sha256(encoded([actor.user_id, identity.collection, identity.entity_id, identity.form_key])).hexdigest()


def scope_hash(actor):
    return hashlib.sha256(encoded([actor.user_id, actor.role, actor.unrestricted, actor.portfolio_ids])).hexdigest()


def _policy(identity):
    if identity.collection == "billing/disputes":
        from ..db.billing_dispute_models import BillingDisputeCaseORM
        from .billing_dispute_drafts import DisputeDraftValues, validate_identity
        try:
            validate_identity(identity)
        except HTTPException as error:
            raise DraftError(error.status_code, "DRAFT_IDENTITY_INVALID", error.detail) from None
        return DisputeDraftValues, BillingDisputeCaseORM.__table__
    name = POLICIES.get(identity.collection)
    if name is None:
        raise DraftError(422, "DRAFT_FORM_UNSUPPORTED", "Dieses Formular unterstützt keine automatische Entwurfssicherung.")
    return getattr(models, name + "Create"), Base.metadata.tables[COLLECTIONS[identity.collection]]


def _fresh(actor, identity):
    if actor is None:
        raise DraftError(401, "DRAFT_AUTH_REQUIRED", "Bitte erneut anmelden.")
    if identity.owner_id is not None and identity.owner_id != actor.user_id:
        raise DraftError(403, "DRAFT_IDENTITY_CHANGED", "Das Formular gehört zu einer anderen Anmeldung. Bitte erneut öffnen.")
    refresh_scope(actor)
    if not may_write_resource(actor.role, identity.collection.split("/")[0]):
        raise DraftError(403, "DRAFT_WRITE_DENIED", "Ihre aktuelle Rolle darf dieses Formular nicht bearbeiten.")
    if not actor.unrestricted and not actor.portfolio_ids:
        raise DraftError(403, "DRAFT_SCOPE_DENIED", "Bitte zuerst ein Portfolio zuweisen lassen.")


def _safe_values(values, allowed):
    if not isinstance(values, dict) or not set(values) <= allowed or set(values) & FORBIDDEN_KEYS:
        raise DraftError(422, "DRAFT_FIELDS_INVALID", "Der Entwurf enthält nicht unterstützte oder geheime Felder.")
    for value in values.values():
        if value is None or isinstance(value, (str, bool, int)):
            continue
        if isinstance(value, float) and math.isfinite(value):
            continue
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            continue
        raise DraftError(422, "DRAFT_VALUES_INVALID", "Nur einfache Formularwerte werden als Entwurf gesichert.")


def _payload(identity, actor, request):
    model, _ = _policy(identity)
    allowed = set(model.model_fields) - FORBIDDEN_KEYS
    _safe_values(request.values, allowed)
    snapshot_fields = allowed if identity.collection == "billing/disputes" else set(getattr(models, POLICIES[identity.collection]).model_fields) - FORBIDDEN_KEYS - {"id", "created_at", "updated_at"}
    _safe_values(request.original_values, snapshot_fields)
    revision = request.edit_revision
    if identity.entity_id:
        try:
            if not isinstance(revision, dict) or set(revision) - {"collection", "id", "updatedAt", "etag", "path"}:
                raise ValueError()
            if revision.get("id") != identity.entity_id or revision.get("collection") != identity.collection:
                raise ValueError()
            utc_datetime(revision["updatedAt"])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DraftError(422, "DRAFT_REVISION_INVALID", "Der ursprüngliche Bearbeitungsstand fehlt oder gehört zu einem anderen Datensatz.") from None
    elif revision is not None:
        raise DraftError(422, "DRAFT_REVISION_INVALID", "Ein neuer Datensatz hat keinen vorhandenen Bearbeitungsstand.")
    value = {"schema": request.schema_signature, "values": request.values, "original_values": request.original_values,
        "edit_revision": revision, "submission_pending": request.submission_pending}
    data = encoded(value)
    if len(data) > limits()[1]:
        raise DraftError(413, "DRAFT_TOO_LARGE", "Der Entwurf überschreitet das eingerichtete Bytebudget. Text verkürzen oder FORM_DRAFT_MAX_BYTES anpassen; Ihr Formular bleibt erhalten.")
    return data


def _visible(store, table, identifier, actor):
    from .portfolio_scope import scoped_clause
    if not isinstance(identifier, str) or not identifier or len(identifier) > 100:
        raise DraftError(422, "DRAFT_REFERENCE_INVALID", "Die Portfolio-/Datensatzzuordnung ist noch unvollständig.")
    if hasattr(store, "db"):
        statement = select(table.c.id).where(table.c.id == identifier)
        criterion = scoped_clause(table, scope=actor)
        if criterion is not None:
            statement = statement.where(criterion)
        return store.db.connection().execute(statement.with_for_update(read=True)).first() is not None
    raw = object.__getattribute__(store, "__dict__")
    row = raw.get(table.name, {}).get(identifier)
    return row is not None and memory_visible(store, table.name, row, scope=actor)


def _resources(store, identity, actor, value):
    if identity.collection == "billing/disputes":
        from .billing_dispute_drafts import validate_resources
        try:
            validate_resources(store, identity, value)
        except HTTPException as error:
            raise DraftError(error.status_code, "DRAFT_REFERENCE_INVALID", error.detail) from None
        return
    _, table = _policy(identity)
    if identity.entity_id and not _visible(store, table, identity.entity_id, actor):
        raise DraftError(404, "DRAFT_RESOURCE_UNAVAILABLE", "Der zugehörige Datensatz ist nicht mehr zugänglich.")
    if hasattr(store, "db"):
        from .portfolio_scope import guard_sql_write
        try:
            guard_sql_write(store.db, table, {key: item for key, item in value.get("values", {}).items() if item != ""},
                entity_id=identity.entity_id, creating=identity.entity_id is None)
        except HTTPException as error:
            raise DraftError(error.status_code, "DRAFT_REFERENCE_DENIED", error.detail) from None
    elif table.name == "tenants" and identity.entity_id and not actor.unrestricted:
        raw = object.__getattribute__(store, "__dict__")
        if any(row.tenant_id == identity.entity_id and not memory_visible(store, "contracts", row, scope=actor)
                for row in raw["contracts"].values()):
            raise DraftError(403, "DRAFT_SHARED_RESOURCE_DENIED", "Ein gemeinsam genutztes Mieterprofil benötigt Zugriff auf alle zugehörigen Portfolios.")
    if not actor.unrestricted and table.name in {"portfolios", "tax_rates", "notification_templates", "escalation_rules"}:
        if identity.entity_id is None or table.name != "portfolios":
            raise DraftError(403, "DRAFT_SCOPE_DENIED", "Dieses Formular benötigt Zugriff auf alle Portfolios.")
    for values in (value.get("values", {}), value.get("original_values", {})):
        for column in table.c:
            identifier = values.get(column.name)
            if identifier in (None, ""):
                continue
            foreign = next(iter(column.foreign_keys), None)
            parent_name = foreign.target_fullname.split(".")[0] if foreign else TEXT_PARENTS.get(column.name)
            parent = Base.metadata.tables.get(parent_name or "")
            if parent is not None and parent_name not in INTERNAL and not _visible(store, parent, identifier, actor):
                raise DraftError(403, "DRAFT_REFERENCE_DENIED", "Eine Entwurfsreferenz liegt außerhalb Ihrer zugänglichen Portfolios.")
        for field, parent_name in csv_parents(table).items():
            for identifier in reference_ids(values.get(field)):
                if not _visible(store, Base.metadata.tables[parent_name], identifier, actor):
                    raise DraftError(403, "DRAFT_REFERENCE_DENIED", "Eine Entwurfsreferenz ist nicht mehr zugänglich.")
        if values.get("entity_id"):
            from .portfolio_scope import RESOURCE_ALIASES
            parent = Base.metadata.tables.get(RESOURCE_ALIASES.get(values.get("entity_type"), ""))
            if parent is None or not _visible(store, parent, values["entity_id"], actor):
                raise DraftError(403, "DRAFT_REFERENCE_DENIED", "Die Entwurfszuordnung ist nicht mehr zugänglich.")
        for field in ("file_url", "photo_url"):
            if values.get(field):
                require_file_access(values[field])


@contextmanager
def _locked(store, actor):
    # Lock order is always account management -> domain memory state. SQL
    # management uses this same permanent marker, including SQLite real DML.
    user_store = auth._user_store
    if hasattr(store, "db"):
        db = store.db
        try:
            if isinstance(user_store, auth.SQLUserStore):
                user_store._lock_management(db)
            elif db.get_bind().dialect.name == "sqlite":
                connection = db.connection()
                if not connection.connection.driver_connection.in_transaction:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
            with scope_context(actor):
                yield
            db.commit()
        except Exception:
            db.rollback()
            raise
    else:
        lock = getattr(user_store, "_lock", None)
        with lock if lock is not None else nullcontext():
            with _memory_lock, scope_context(actor):
                yield


def _record(store, key, user_id):
    if hasattr(store, "db"):
        table = cast(Table, FormDraftORM.__table__)
        row = store.db.connection().execute(select(table).where(table.c.id == key, table.c.user_id == user_id)).mappings().first()
        return dict(row) if row else None
    return object.__getattribute__(store, "__dict__").get("_form_drafts", {}).get(key)


def _delete(store, key, user_id, revision):
    if hasattr(store, "db"):
        table = cast(Table, FormDraftORM.__table__)
        return store.db.connection().execute(delete(table).where(table.c.id == key, table.c.user_id == user_id, table.c.revision == revision)).rowcount == 1
    state = object.__getattribute__(store, "__dict__").setdefault("_form_drafts", {})
    if state.get(key, {}).get("revision") != revision:
        return False
    del state[key]
    return True


def _read(row, key, actor):
    if row["scope_hash"] != scope_hash(actor):
        raise DraftError(403, "DRAFT_SCOPE_CHANGED", "Ihre Portfolio-/Rollenberechtigungen haben sich geändert. Der frühere Entwurf darf nicht wiederhergestellt werden.")
    try:
        return json.loads(form_draft_crypto.decrypt(row["payload"], key.encode("ascii")))
    except (form_draft_crypto.DraftCryptoError, IBANEncryptionError, ValueError, UnicodeError):
        raise DraftError(503, "DRAFT_ENCRYPTION_UNAVAILABLE", "Der gespeicherte Entwurf kann nicht sicher gelesen werden. Vollständige stabile Verschlüsselungsschlüssel wiederherstellen; der Entwurf wurde nicht überschrieben.") from None


def _conflict():
    return DraftError(409, "DRAFT_CONFLICT", "Ein anderes Fenster hat diesen Entwurf verändert. Ihre Formularwerte bleiben erhalten; prüfen Sie den gespeicherten Entwurf bewusst.")


def form_draft(store, identity: DraftIdentity, actor, *, write: DraftWrite | None = None, remove_revision=None):
    _policy(identity)
    limits()
    _fresh(actor, identity)
    key = identity_key(identity, actor)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with _locked(store, actor):
        _fresh(actor, identity)
        row = _record(store, key, actor.user_id)
        if row and row["expires_at"] <= now:
            _delete(store, key, actor.user_id, row["revision"])
            row = None
        if remove_revision is not None:
            # Own discarded ciphertext needs no decryption or old grants. No
            # foreign principal can address this key; stale CAS never deletes.
            if row and not _delete(store, key, actor.user_id, remove_revision):
                raise _conflict()
            _fresh(actor, identity)
            return {"discarded": row is not None}
        if write is None:
            if row is None:
                return {"draft": None}
            value = _read(row, key, actor)
            _resources(store, identity, actor, value)
            _fresh(actor, identity)
            return {"draft": {"revision": row["revision"], "updated_at": row["updated_at"].isoformat() + "Z",
                "expires_at": row["expires_at"].isoformat() + "Z", **value}}
        if row and row["revision"] != write.expected_revision or not row and write.expected_revision is not None:
            raise _conflict()
        data = _payload(identity, actor, write)
        value = json.loads(data)
        _resources(store, identity, actor, value)
        if row is not None:
            _read(row, key, actor)  # Never overwrite unauthenticated old data.
        try:
            ciphertext = form_draft_crypto.encrypt(data, key.encode("ascii"))
        except (form_draft_crypto.DraftCryptoError, IBANEncryptionError):
            raise DraftError(503, "DRAFT_ENCRYPTION_UNAVAILABLE", "Entwurfsschutz benötigt gültige stabile Verschlüsselungsschlüssel. Ihre Formularwerte bleiben erhalten; bitte Konfiguration prüfen.") from None
        result = {"id": key, "user_id": actor.user_id, "collection": identity.collection, "entity_id": identity.entity_id,
            "form_key": identity.form_key, "scope_hash": scope_hash(actor), "revision": str(uuid4()), "payload": ciphertext,
            "updated_at": now, "expires_at": now + timedelta(days=limits()[0])}
        _fresh(actor, identity)
        if hasattr(store, "db"):
            table = cast(Table, FormDraftORM.__table__)
            if row:
                changed = store.db.connection().execute(update(table).where(table.c.id == key, table.c.user_id == actor.user_id,
                    table.c.revision == write.expected_revision).values(**result)).rowcount
                if changed != 1:
                    raise _conflict()
            else:
                try:
                    store.db.connection().execute(insert(table).values(**result))
                except IntegrityError:
                    raise _conflict() from None
            _fresh(actor, identity)
        else:
            object.__getattribute__(store, "__dict__").setdefault("_form_drafts", {})[key] = result
        return {"revision": result["revision"], "updated_at": now.isoformat() + "Z", "expires_at": result["expires_at"].isoformat() + "Z"}


def guard_destructive_reset(store):
    if hasattr(store, "db"):
        # Already retained private data needs no lock/DML to refuse. The second
        # read below still excludes an autosave committed during serialization.
        if store.db.connection().execute(select(FormDraftORM.__table__.c.id).limit(1)).first() is not None:
            raise ValueError("Persönliche Formularentwürfe sind vorhanden. Vor Teilimport oder Zurücksetzen ausdrücklich verwerfen oder vollständige Recovery separat wiederherstellen.")
        # Share the draft writer's lock order before checking the journal. A
        # concurrent autosave must finish before a destructive maintenance read.
        user_store = auth._user_store
        if isinstance(user_store, auth.SQLUserStore):
            user_store._lock_management(store.db)
        connection = store.db.connection()
        if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name == "postgresql":
            connection.exec_driver_sql("LOCK TABLE form_drafts IN SHARE ROW EXCLUSIVE MODE")
        found = store.db.connection().execute(select(FormDraftORM.__table__.c.id).limit(1)).first() is not None
    else:
        found = bool(object.__getattribute__(store, "__dict__").get("_form_drafts"))
    if found:
        raise ValueError("Persönliche Formularentwürfe sind vorhanden. Vor Teilimport oder Zurücksetzen ausdrücklich verwerfen oder vollständige Recovery separat wiederherstellen.")
