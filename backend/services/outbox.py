"""Manually claimed durable SMTP outbox: no scheduler and no automatic retry."""

import hashlib
import hmac
import json
import secrets
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .. import auth
from ..db.orm_models import PortfolioORM
from ..db.outbox_models import OutboxCommandORM, OutboxEventORM, OutboxMessageORM
from ..outbox_models import OutboxCommand, OutboxCreate, OutboxDecision
from ..permissions import may_write_resource
from . import email_service as mail
from . import outbox_state as state
from .integrations.manager import integration_manager
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user, scoped_clause

DATE_FIELDS = {"created_at", "updated_at", "lease_until", "human_decided_at"}
LEASE_SECONDS = 90  # Exceeds the SMTP watchdog (<=60s) and process cleanup budget.


def utcnow():
    return datetime.now(timezone.utc)


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(",", ":"))


def encode_state(value):
    data = asdict(value)
    return encoded({key: item.isoformat() if isinstance(item, datetime) else item for key, item in data.items()})


def decode_state(row):
    try:
        data = json.loads(row.state_json)
        for field in DATE_FIELDS:
            if data.get(field) is not None:
                data[field] = datetime.fromisoformat(data[field])
                if data[field].utcoffset() is None:
                    raise ValueError
        value = state.OutboxMessage(**data)
        if (value.revision != row.revision or value.message_id != row.message_id
                or value.idempotency_scope != row.portfolio_id or value.idempotency_key != row.idempotency_key
                or value.state not in {"ready", "claimed", "sent", "failed", "unknown"}
                or value.phase not in {"idle", "pre_data", "data"}
                or (value.state == "claimed") != bool(value.claim_owner and value.claim_token and value.lease_until)
                or (value.state == "claimed") != (value.phase != "idle")
                or type(value.attempt_no) is not int or value.attempt_no < 0):
            raise ValueError
        return value
    except (TypeError, ValueError, KeyError):
        raise HTTPException(409, "outbox_state_integrity: message state could not be verified") from None


def database(store):
    if not hasattr(store, "db"):
        raise HTTPException(503, "outbox_requires_persistent_sql: configure the persistent database")
    return store.db


def fresh_scope(actor_id, *, write=False, captured=None):
    if captured is not None:
        refresh_scope(captured)
    user = auth.get_user_by_id(actor_id)
    if not user or not user["is_active"] or (write and not may_write_resource(user["role"], "messages")):
        raise HTTPException(403, "outbox_permission_changed: communication permission is required")
    return scope_from_user(user)


@contextmanager
def authorized(store, actor_id, *, write=False, captured=None):
    selected = fresh_scope(actor_id, write=write, captured=captured or current_scope())
    with scope_context(selected):
        try:
            yield selected
        except BaseException:
            database(store).rollback()
            raise


def portfolio(db, portfolio_id):
    query = select(PortfolioORM.id).where(PortfolioORM.id == portfolio_id)
    predicate = scoped_clause(PortfolioORM)
    if predicate is not None:
        query = query.where(predicate)
    if db.scalar(query) is None:
        raise HTTPException(404, "Portfolio not found")


def message_row(db, identifier):
    row = db.scalar(select(OutboxMessageORM).where(OutboxMessageORM.id == identifier)
                    .execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "Outbox message not found")
    portfolio(db, row.portfolio_id)
    return row


def read_message(row):
    value = decode_state(row)
    result = asdict(value)
    for name in ("idempotency_key", "idempotency_scope", "claim_token"):
        result.pop(name)
    return {"id": row.id, "portfolio_id": row.portfolio_id, "actor_id": row.actor_id,
        "snapshot": json.loads(row.snapshot_json), "snapshot_sha256": row.snapshot_sha256,
        "wire_sha256": row.wire_sha256, "wire_size": len(row.wire),
        **{key: item.isoformat() if isinstance(item, datetime) else item for key, item in result.items()}}


def configuration(*, require_enabled=False):
    enabled, values = integration_manager._snapshot("email")
    try:
        config = mail.EmailConfig.from_mapping(values)
    except mail.EmailConfigError:
        raise HTTPException(409, "outbox_smtp_not_configured: configure SMTP before reviewing a message") from None
    if require_enabled and not enabled:
        raise HTTPException(409, "outbox_smtp_disabled: enable the SMTP integration before sending")
    return enabled, config


def public_configuration(actor_id):
    fresh_scope(actor_id)
    try:
        enabled, config = configuration()
        return {"configured": True, "enabled": enabled, "sender_address": config.from_address,
                "sender_name": config.from_name, "maximum_wire_bytes": mail.MAX_MESSAGE_BYTES,
                "timeout_seconds": config.timeout_seconds}
    except HTTPException:
        return {"configured": False, "enabled": False, "maximum_wire_bytes": mail.MAX_MESSAGE_BYTES}


def commit(db):
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "outbox_database_unavailable: the journal was not committed") from None


def event(db, row, value, actor_id, kind, *, note=None):
    db.add(OutboxEventORM(id=str(uuid4()), portfolio_id=row.portfolio_id, message_id=row.id,
        actor_id=actor_id, revision=value.revision, attempt_no=value.attempt_no, kind=kind,
        state=value.state, phase=value.phase, code=value.last_code, note=note,
        created_at=value.updated_at.replace(tzinfo=None)))


def create_message(store, command: OutboxCreate, actor_id):
    db = database(store)
    with authorized(store, actor_id, write=True):
        portfolio(db, command.portfolio_id)
        snapshot = command.model_dump(exclude={"idempotency_key"})
        content = encoded(snapshot)
        fingerprint = hashlib.sha256(content.encode("ascii")).hexdigest()
        key = actor_id + ":" + command.idempotency_key
        def replay(row):
            if row.snapshot_sha256 != fingerprint:
                raise HTTPException(409, "outbox_reference_reused: this reference belongs to different reviewed content")
            return read_message(row)
        prior = db.scalar(select(OutboxMessageORM).where(OutboxMessageORM.idempotency_key == key))
        if prior:
            return replay(prior)
        _, config = configuration()
        if (command.sender_address, command.sender_name) != (config.from_address, config.from_name):
            raise HTTPException(409, "outbox_sender_changed: review the current sender before saving")
        now = utcnow()
        value = state.new_message(idempotency_scope=command.portfolio_id, idempotency_key=key,
                                 message_id_secret=secrets.token_bytes(32), now=now)
        html = "<pre>" + escape(command.body_text) + "</pre>"
        try:
            if max(len(html), len(command.body_text)) > mail.MAX_MESSAGE_BYTES:
                raise mail.EmailConfigError("message_too_large")
            wire = mail._wire_message(config, command.recipient, command.subject, html, command.body_text,
                                      message_id=value.message_id, date_header=format_datetime(now, usegmt=True))
        except (mail.EmailConfigError, UnicodeError) as exc:
            detail = ("outbox_message_too_large: adjust the content or split it into separately reviewed messages; nothing was truncated"
                if str(exc) == "message_too_large" else "outbox_invalid_content: check the recipient, subject and message text")
            raise HTTPException(422, detail) from None
        row = OutboxMessageORM(id=str(uuid4()), portfolio_id=command.portfolio_id, idempotency_key=key,
            actor_id=actor_id, message_id=value.message_id, snapshot_json=content, snapshot_sha256=fingerprint,
            wire=wire, wire_sha256=hashlib.sha256(wire).hexdigest(), state_json=encode_state(value),
            revision=0, created_at=now.replace(tzinfo=None), updated_at=now.replace(tzinfo=None))
        db.add(row)
        try:
            db.flush([row])
            event(db, row, value, actor_id, "reviewed")
            fresh_scope(actor_id, write=True, captured=current_scope())
            db.commit()
            return read_message(row)
        except IntegrityError:
            db.rollback()
            prior = db.scalar(select(OutboxMessageORM).where(OutboxMessageORM.idempotency_key == key))
            if prior is None:
                raise HTTPException(409, "outbox_review_conflict: reload the portfolio") from None
            return replay(prior)
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(503, "outbox_database_unavailable: reviewed message was not committed") from None


def get_message(store, identifier, actor_id):
    with authorized(store, actor_id):
        return read_message(message_row(database(store), identifier))


def list_messages(store, portfolio_id, actor_id, offset=0, limit=25):
    with authorized(store, actor_id):
        db = database(store)
        portfolio(db, portfolio_id)
        query = select(OutboxMessageORM).where(OutboxMessageORM.portfolio_id == portfolio_id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(OutboxMessageORM.created_at.desc(), OutboxMessageORM.id.desc())
            .offset(offset).limit(limit)).all()
        return {"total": total, "items": [read_message(row) for row in rows]}


def list_events(store, identifier, actor_id, offset=0, limit=100):
    with authorized(store, actor_id):
        db = database(store)
        message_row(db, identifier)
        query = select(OutboxEventORM).where(OutboxEventORM.message_id == identifier)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(OutboxEventORM.revision.desc(), OutboxEventORM.id.desc())
            .offset(offset).limit(limit)).all()
        return {"total": total, "items": [{column.key: (
            row.created_at.replace(tzinfo=timezone.utc).isoformat() if column.key == "created_at" else getattr(row, column.key)
        ) for column in row.__table__.columns} for row in rows]}


def cas(db, row, old, proposed, actor_id, kind, *, note=None):
    if proposed.revision != old.revision + 1:
        raise HTTPException(409, "outbox_invalid_transition")
    result = db.execute(update(OutboxMessageORM).where(OutboxMessageORM.id == row.id,
        OutboxMessageORM.revision == old.revision, OutboxMessageORM.state_json == encode_state(old))
        .values(state_json=encode_state(proposed), revision=proposed.revision,
                updated_at=proposed.updated_at.replace(tzinfo=None)).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(412, "outbox_revision_changed: reload and review the current message")
    event(db, row, proposed, actor_id, kind, note=note)
    db.expire(row)


def existing_command(db, row, command, actor_id, kind):
    key = actor_id + ":" + command.idempotency_key
    request = encoded(command.model_dump(exclude={"idempotency_key"}))
    existing = db.scalar(select(OutboxCommandORM).where(OutboxCommandORM.idempotency_key == key))
    if existing:
        if existing.message_id != row.id or existing.kind != kind or existing.request_json != request:
            raise HTTPException(409, "outbox_reference_reused: command reference belongs to another action")
        return existing, True
    if row.revision != command.expected_revision:
        raise HTTPException(412, "outbox_revision_changed: reload and review the current message")
    record = OutboxCommandORM(id=str(uuid4()), portfolio_id=row.portfolio_id, message_id=row.id,
        idempotency_key=key, actor_id=actor_id, kind=kind, request_json=request, created_at=utcnow().replace(tzinfo=None))
    db.add(record)
    return record, False


def replay_result(record, row):
    return json.loads(record.result_json) if record.result_json is not None else read_message(row)


def transition_error(operation):
    try:
        return operation()
    except state.OutboxError as exc:
        raise HTTPException(409, "outbox_" + exc.code) from None


def claim_message(store, identifier, command: OutboxCommand, actor_id):
    db = database(store)
    with authorized(store, actor_id, write=True) as captured:
        row = message_row(db, identifier)
        try:
            record, replay = existing_command(db, row, command, actor_id, "send")
            if replay:
                return replay_result(record, row), None
            old = decode_state(row)
            proposed = transition_error(lambda: state.claim(old, owner=actor_id, claim_token=str(uuid4()),
                                                    now=utcnow(), lease_seconds=LEASE_SECONDS))
            record.claim_token = proposed.claim_token
            cas(db, row, old, proposed, actor_id, "claim")
            fresh_scope(actor_id, write=True, captured=captured)
            db.commit()
            return read_message(row), (record.id, proposed.claim_token, captured)
        except (IntegrityError, HTTPException) as exc:
            if isinstance(exc, HTTPException) and exc.status_code != 412:
                raise
            db.rollback()
            current = message_row(db, identifier)
            record, replay = existing_command(db, current, command, actor_id, "send")
            if replay:
                return replay_result(record, current), None
            db.expunge(record)
            raise HTTPException(412, "outbox_revision_changed: reload and review the current message") from None
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(503, "outbox_database_unavailable: claim was not committed") from None


def mark_data(store, identifier, actor_id, token, captured, config):
    db = database(store)
    with authorized(store, actor_id, write=True, captured=captured):
        if configuration(require_enabled=True)[1] != config:
            raise HTTPException(409, "outbox_transport_changed: review the active SMTP configuration")
        row = message_row(db, identifier)
        old = decode_state(row)
        proposed = transition_error(lambda: state.mark_data_started(old, owner=actor_id, claim_token=token, now=utcnow()))
        cas(db, row, old, proposed, actor_id, "data_checkpoint")
        fresh_scope(actor_id, write=True, captured=captured)
        commit(db)


def finish_owned(store, identifier, actor_id, token, command_id, outcome):
    """Narrow internal completion after transport: no new rights or network work.

    Even a revoked sender's exact owned claim must retain its factual outcome.
    All other message reads/commands stay under fresh authorization.
    """
    db = database(store)
    with scope_context(None):
        db.rollback()  # Discard any failed/uncommitted checkpoint; read durable state only.
        row = db.get(OutboxMessageORM, identifier, populate_existing=True)
        if row is None:
            raise HTTPException(409, "outbox_claim_missing")
        old = decode_state(row)
        proposed = transition_error(lambda: state.finish_attempt(old, owner=actor_id, claim_token=token,
                                                                 outcome=outcome, now=utcnow()))
        record = db.get(OutboxCommandORM, command_id, populate_existing=True)
        if (not record or record.message_id != identifier or record.actor_id != actor_id
                or record.kind != "send" or record.claim_token != token):
            raise HTTPException(409, "outbox_claim_command_mismatch")
        cas(db, row, old, proposed, actor_id, "transport_result")
        result = read_message(row)
        record.result_json = encoded(result)
        commit(db)
        return result


def send_message(store, identifier, command: OutboxCommand, actor_id):
    # Validate fresh permissions and config before claiming; no network here.
    with authorized(store, actor_id, write=True):
        row = message_row(database(store), identifier)
        prior, replay = existing_command(database(store), row, command, actor_id, "send")
        if replay:
            return replay_result(prior, row)
        database(store).expunge(prior)  # Claim owns the sole command insertion.
        _, config = configuration(require_enabled=True)
        snapshot = json.loads(row.snapshot_json)
        if (snapshot["sender_address"], snapshot["sender_name"]) != (config.from_address, config.from_name):
            raise HTTPException(409, "outbox_sender_changed: create a newly reviewed message")
        wire = row.wire
        if (not hmac.compare_digest(hashlib.sha256(wire).hexdigest(), row.wire_sha256)
                or not hmac.compare_digest(hashlib.sha256(row.snapshot_json.encode("ascii")).hexdigest(), row.snapshot_sha256)):
            raise HTTPException(409, "outbox_snapshot_integrity: reviewed content could not be verified")
    initial, claimed = claim_message(store, identifier, command, actor_id)
    if claimed is None:
        return initial
    command_id, token, captured = claimed
    denied = []
    def checkpoint():
        try:
            mark_data(store, identifier, actor_id, token, captured, config)
        except Exception as exc:
            denied.append(exc)
            raise
    try:
        fresh_scope(actor_id, write=True, captured=captured)
        result = mail.submit_prepared_email(snapshot["recipient"], wire, config=config, before_data=checkpoint)
    except BaseException:
        # A local interrupted caller cannot assume the relay declined DATA.
        with scope_context(None):
            current = decode_state(database(store).get(OutboxMessageORM, identifier, populate_existing=True))
        outcome = state.TransportOutcome("unknown" if current.phase == "data" else "safe_failure", "caller_interrupted")
        finish_owned(store, identifier, actor_id, token, command_id, outcome)
        raise
    outcome = state.TransportOutcome("accepted" if result.status == "accepted" else
        "unknown" if result.status == "unknown" else "safe_failure", result.code)
    completed = finish_owned(store, identifier, actor_id, token, command_id, outcome)
    fresh_scope(actor_id, write=True, captured=captured)
    if denied:
        error = denied[0]
        if isinstance(error, HTTPException):
            raise error
        raise HTTPException(503, "outbox_checkpoint_failed: no DATA was released") from None
    return completed


def decide(store, identifier, command: OutboxDecision | OutboxCommand, actor_id, *, recover=False):
    db = database(store)
    kind = "recover" if recover else "decision"
    with authorized(store, actor_id, write=True) as captured:
        row = message_row(db, identifier)
        record, replay = existing_command(db, row, command, actor_id, kind)
        if replay:
            return replay_result(record, row)
        old = decode_state(row)
        note = None
        if recover:
            proposed = transition_error(lambda: state.recover_expired_claim(old, now=utcnow()))
        else:
            assert isinstance(command, OutboxDecision)
            note = command.note
            if old.state == "unknown" and command.action != "cancel":
                proposed = transition_error(lambda: state.resolve_unknown(old, action=command.action,
                    actor=actor_id, note=note, now=utcnow()))
            elif (old.state == "failed" and command.action == "retry") or (old.state == "ready" and command.action == "cancel"):
                proposed = replace(old, state="ready" if command.action == "retry" else "failed",
                    revision=old.revision + 1, updated_at=utcnow(), last_code="human:" + command.action,
                    human_action=command.action, human_actor=actor_id, human_note=note, human_decided_at=utcnow())
            else:
                raise HTTPException(409, "outbox_decision_not_allowed: review the current message state")
        cas(db, row, old, proposed, actor_id, kind, note=note)
        fresh_scope(actor_id, write=True, captured=captured)
        result = read_message(row)
        record.result_json = encoded(result)
        commit(db)
        return result
