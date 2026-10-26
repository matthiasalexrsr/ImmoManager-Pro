"""Portal transactions and current relation checks, independent of internal auth."""
import hashlib
from contextlib import contextmanager
from datetime import datetime
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...config import settings
from ...db.external_portal_models import (
    PortalCommandORM,
    PortalEventORM,
    PortalGrantORM,
    PortalIdentityORM,
    PortalSessionORM,
)
from ...db.orm_models import ContactORM, ContractORM, OwnershipShareORM, PropertyORM, TenantORM, UnitORM
from ...domain.clock import local_today
from .. import document_versions as archive
from ..data_transfer.common import digest
from ..integrations import connection_storage as db
from ..maintenance_rows import Rows
from ..portfolio_scope import scope_context, scope_from_user
from ..workspace_contexts import bound_actor

COOKIE = "immo_portal_session"
COOKIE_PATH = "/api/v1/portal"
LOCK = 725627503


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def origin():
    value = settings.portal_public_url.rstrip("/")
    parsed = urlsplit(value)
    if not settings.portal_enabled:
        raise HTTPException(503, "Das externe Portal ist noch nicht aktiviert.")
    try:
        local = parsed.hostname == "localhost" or ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, "Eine gültige öffentliche Portaladresse ohne Pfad muss konfiguriert werden.")
    if parsed.scheme != "https" and not (settings.portal_local_test_mode and local):
        raise HTTPException(503, "Der öffentliche Portalbetrieb benötigt eine HTTPS-Adresse.")
    return value


def check_transport(request, *, write=False):
    expected = origin()
    if request.headers.get("authorization"):
        raise HTTPException(401, "Das externe Portal verwendet ausschließlich seine eigene Portalsitzung.")
    if request.url.scheme != "https":
        try:
            local = ip_address(request.client.host).is_loopback
        except (ValueError, AttributeError):
            local = False
        if not settings.portal_local_test_mode or not local or urlsplit(expected).scheme != "http":
            raise HTTPException(403, "Portalzugriff erfordert HTTPS.")
    if str(request.base_url).rstrip("/") != expected:
        raise HTTPException(403, "Portaladresse stimmt nicht mit der konfigurierten Adresse überein.")
    if write and (request.headers.get("origin") != expected or request.headers.get("x-portal-client") != "web-v1"):
        raise HTTPException(403, "Die Herkunft dieser Portalaktion ist nicht bestätigt.")


def _serialize(unit):
    if unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
        # Customer imports/exports take this fence before their table locks.
        unit.db.execute(text("SELECT pg_advisory_xact_lock(725627501)"))
        unit.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})


@contextmanager
def admin_work(store, actor_id):
    with archive.work(store, actor_id, write_areas=("/portal-admin",)) as unit:
        if unit.user["role"] not in ("eigentuemer", "verwalter"):
            raise HTTPException(403, "Portalverwaltung benötigt Eigentümer- oder Verwalterrechte.")
        _serialize(unit)
        with bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            yield unit


@contextmanager
def raw_work(store):
    """Private writer: only explicit portal grant predicates authorize its data."""
    with scope_context(None):
        if not hasattr(store, "db"):
            journal = archive.memory_archive(store)
            with journal.lock:
                unit = archive.Unit(store, None, {}, journal)
                try:
                    yield unit
                except BaseException:
                    unit.rollback()
                    raise
            return
        from ...dependencies import release_request_read_connection
        from ...repositories.sql_store import SQLAlchemyStore
        from ..sqlite_writes import sqlite_write_gate
        bind = store.db.get_bind()
        release_request_read_connection(store)
        with sqlite_write_gate(bind, "portal"):
            session = Session(bind=getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
            try:
                archive.begin_writer(session)
                unit = archive.Unit(SQLAlchemyStore(session), session, {}, None)
                _serialize(unit)
                yield unit
                session.commit()
            except IntegrityError:
                session.rollback()
                raise HTTPException(409, "Der Portalstand hat sich geändert. Bitte neu laden.") from None
            except BaseException:
                session.rollback()
                raise
            finally:
                session.close()


def rows(unit, model, **filters):
    if unit.db is not None:
        return list(unit.db.scalars(select(model).filter_by(**filters).order_by(model.id)))
    return sorted((row for row in db.memory(unit, model).values() if all(getattr(row, key) == value for key, value in filters.items())), key=lambda row: row.id)


def _locked(unit, model, identifier):
    if unit.db is not None and identifier:
        unit.db.scalar(select(model).where(model.id == identifier).with_for_update(read=True).execution_options(populate_existing=True))


def binding(unit, kind, party_id, relation_id):
    source = Rows.of(unit)
    table = "contracts" if kind == "tenant" else "ownership_shares"
    before = source.require(table, relation_id, "Vertrags- oder Eigentumsverhältnis nicht gefunden.")
    # Match the archive's party -> property -> unit -> contract lock order.
    # Reload the relation under its lock, so an intervening reassignment fails.
    _locked(unit, TenantORM if kind == "tenant" else ContactORM, party_id)
    _locked(unit, PropertyORM, before.property_id)
    _locked(unit, UnitORM, before.unit_id)
    _locked(unit, ContractORM if kind == "tenant" else OwnershipShareORM, relation_id)
    relation = source.require(table, relation_id, "Vertrags- oder Eigentumsverhältnis nicht gefunden.")
    if (before.property_id, before.unit_id) != (relation.property_id, relation.unit_id):
        raise HTTPException(409, "Die Zuordnung wurde während der Prüfung geändert. Bitte neu laden.")
    if kind == "tenant":
        if relation.tenant_id != party_id or relation.status == "draft":
            raise HTTPException(409, "Die geprüfte Partei gehört nicht zu diesem wirksamen Vertrag.")
        party = unit.store.get_tenant(party_id)
        fields = dict(kind=kind, party_id=party_id, relation_id=relation.id, property_id=relation.property_id, unit_id=relation.unit_id)
    else:
        if relation.owner_contact_id != party_id or (relation.valid_from and relation.valid_from > local_today()) or (relation.valid_to and relation.valid_to < local_today()):
            raise HTTPException(409, "Das Eigentumsverhältnis ist für diese Partei aktuell nicht wirksam.")
        party = unit.store.get_contact(party_id)
        if party.contact_type != "owner":
            raise HTTPException(409, "Die Partei ist kein Eigentümerkontakt.")
        fields = dict(kind=kind, party_id=party_id, relation_id=relation.id, property_id=relation.property_id, unit_id=relation.unit_id)
    prop = source.require("properties", relation.property_id, "Immobilie nicht gefunden.")
    if relation.unit_id:
        place = source.require("units", relation.unit_id, "Einheit nicht gefunden.")
        if place.property_id != prop.id:
            raise HTTPException(409, "Einheit und Immobilie gehören nicht zusammen.")
    return {**fields, "portfolio_id": prop.portfolio_id}, party


def grant(unit, identifier, identity_id=None, *, active=True):
    item = db.row(unit, PortalGrantORM, identifier, lock=True, required=False)
    if item is None or (identity_id and item.identity_id != identity_id) or (active and not item.active):
        raise HTTPException(404, "Portalzuordnung nicht verfügbar.")
    current, _ = binding(unit, item.kind, item.tenant_id or item.contact_id, item.contract_id or item.ownership_id)
    if current != item.binding or current["portfolio_id"] != item.portfolio_id:
        raise HTTPException(409, "Die Zuordnung wurde fachlich geändert. Ein neuer geprüfter Portalzugang ist erforderlich.")
    return item


@contextmanager
def external_work(store, token):
    if not token or len(token) > 100:
        raise HTTPException(401, "Bitte am Portal anmelden.")
    with raw_work(store) as unit:
        session = db.find_one(unit, PortalSessionORM, token_sha256=token_hash(token), lock=True)
        if session is None or session.revoked_at or session.expires_at <= db.now():
            raise HTTPException(401, "Portalsitzung abgelaufen oder widerrufen.")
        identity = db.row(unit, PortalIdentityORM, session.identity_id, lock=True)
        if not identity.active or identity.revision != session.identity_revision:
            raise HTTPException(401, "Portalzugang deaktiviert. Bitte die Verwaltung kontaktieren.")
        unit.user = {"id": "portal:" + identity.id}
        yield unit, identity, session


def replay(unit, operation, command):
    previous = db.find_one(unit, PortalCommandORM, actor_id=unit.actor_id, idempotency_key=command.idempotency_key)
    if previous is not None:
        if previous.operation != operation or previous.request_sha256 != digest(command.model_dump(mode="json")):
            raise HTTPException(409, "Diese Wiederholungskennung gehört zu einer anderen Portalaktion.")
        return previous.response
    return None


def receipt(unit, operation, command, response):
    db.put(unit, PortalCommandORM, {"id": str(uuid4()), "actor_id": unit.actor_id, "idempotency_key": command.idempotency_key,
        "operation": operation, "request_sha256": digest(command.model_dump(mode="json")), "response": response, "created_at": db.now()})
    return response


def event(unit, grant_id, kind, reason, detail=None):
    db.put(unit, PortalEventORM, {"id": str(uuid4()), "grant_id": grant_id, "actor_id": unit.actor_id, "kind": kind,
        "reason": reason, "detail": detail or {}, "created_at": db.now()})


def public(row, fields):
    return {key: value.isoformat() if isinstance(value := getattr(row, key), datetime) else value for key in fields}
