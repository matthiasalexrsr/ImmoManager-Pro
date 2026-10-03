"""Independent short SQL transactions; no network calls or RAM retention cap."""

import hashlib
import hmac
import secrets
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Table, and_, delete, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from ...db.integration_history_models import (
    IntegrationHistoryClearORM,
    IntegrationHistoryHeadORM,
    IntegrationRunChunkORM,
    IntegrationRunEventORM,
    IntegrationRunORM,
)
from ...db.integration_history_schema import ensure_history_schema
from .history_crypto import (
    CHUNK_BYTES,
    canonical,
    decrypt,
    digest,
    encrypt,
    event_identity,
    ring_for,
    run_identity,
    stamp,
)
from .history_types import HistoryActor, HistoryError, HistoryLimits, RunTicket
from .history_validation import (
    TERMINAL,
    bounded_projection,
    check_artifacts,
    check_deadline,
    check_row,
    check_transition,
    checked_json,
    verified_artifacts,
)

HEAD = cast(Table, IntegrationHistoryHeadORM.__table__)
RUN = cast(Table, IntegrationRunORM.__table__)
EVENT = cast(Table, IntegrationRunEventORM.__table__)
CHUNK = cast(Table, IntegrationRunChunkORM.__table__)
CLEAR = cast(Table, IntegrationHistoryClearORM.__table__)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SQLIntegrationHistoryStore:
    def __init__(self, session_factory, *, limits=None, keyring=None):
        self.factory = session_factory
        self.limits = limits or HistoryLimits()
        self.keyring = keyring

    def ring(self):
        return self.keyring if self.keyring is not None else ring_for()

    @contextmanager
    def connection(self, *, write=False, actor=None, passthrough_body=False):
        # A factory gives an unscoped independent Session, never the domain
        # request's scoped registry. Use its bind, close it, own the Connection.
        with self.factory() as session:
            engine = session.get_bind()
        from ... import auth

        account_lock = getattr(auth._user_store, "_lock", None) if write else None
        body_passthrough = False
        try:
            # The account lifetime is OUTSIDE transaction exit so a mutex taken
            # after SQLite BEGIN remains held through the actual DB commit.
            with ExitStack() as account_lifetime:
                if account_lock is not None and engine.dialect.name != "sqlite":
                    account_lifetime.enter_context(account_lock)
                with engine.connect() as connection, connection.begin():
                    # PostgreSQL/SQLite timeout integer uses a signed 32-bit
                    # native contract. Larger configured overall budgets remain
                    # valid; individual statements use that maximum.
                    milliseconds = max(1, int(min(self.limits.timeout_seconds, 2147483.647) * 1000))
                    if connection.dialect.name == "sqlite":
                        connection.exec_driver_sql("PRAGMA busy_timeout=" + str(milliseconds))
                        if write:
                            connection.exec_driver_sql("BEGIN IMMEDIATE")
                            if account_lock is not None:
                                account_lifetime.enter_context(account_lock)
                    elif connection.dialect.name == "postgresql":
                        connection.exec_driver_sql("SET LOCAL statement_timeout = " + str(milliseconds))
                        if not write:
                            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    if not ensure_history_schema(connection):
                        raise HistoryError("HISTORY_NOT_CONFIGURED")
                    if write and actor is not None and actor.origin == "authenticated_request" and isinstance(auth._user_store, auth.SQLUserStore):
                        # The actual configured auth carrier must be in this
                        # shared database. Never seed or repair a missing marker.
                        with auth._user_store._session_factory() as account_session:
                            if account_session.get_bind() is not engine:
                                raise HistoryError("HISTORY_NOT_CONFIGURED")
                        from ...db.auth_models import AuthSetupORM

                        carrier = cast(Table, AuthSetupORM.__table__)
                        if connection.execute(update(carrier).where(carrier.c.id == 1).values(completed_at=carrier.c.completed_at)).rowcount != 1:
                            raise HistoryError("HISTORY_NOT_CONFIGURED")
                    try:
                        yield connection
                    except BaseException:
                        body_passthrough = passthrough_body
                        raise
        except SQLAlchemyError:
            if body_passthrough:
                raise
            raise HistoryError("HISTORY_WRITE_FAILED") from None
        except (ValueError, TypeError, KeyError, OverflowError):
            if body_passthrough:
                raise
            raise HistoryError("HISTORY_CORRUPT") from None

    def _head(self, connection, integration_id):
        if connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            statement = pg_insert(HEAD)
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            statement = cast(Any, sqlite_insert(HEAD))
        connection.execute(statement.values(integration_id=integration_id, run_sequence=0, event_sequence=0,
            clear_epoch=0, active_runs=0, history_started_at=now()).on_conflict_do_nothing(index_elements=["integration_id"]))
        return dict(connection.execute(select(HEAD).where(HEAD.c.integration_id == integration_id).with_for_update()).mappings().one())

    def _append(self, connection, run, head, state, artifacts, previous=None, *, deadline=None):
        ring = self.ring()
        encoded = {kind: canonical(value) for kind, value in artifacts.items()}
        if any(len(value) > self.limits.artifact_bytes for value in encoded.values()):
            raise HistoryError("HISTORY_BUDGET_EXCEEDED", 413)
        manifest: dict[str, dict[str, Any]] = {kind: {"bytes": len(raw), "chunks": max(1, (len(raw) + CHUNK_BYTES - 1) // CHUNK_BYTES), "sha256": hashlib.sha256(raw).hexdigest()} for kind, raw in encoded.items()}
        event = dict(id=uuid4().hex, run_id=run["id"], integration_id=run["integration_id"],
            event_number=1 if previous is None else previous["event_number"] + 1, journal_sequence=head["event_sequence"] + 1,
            state=state, success=artifacts.get("response", {}).get("success"), created_at=now(), previous_hash="" if previous is None else previous["event_hash"], manifest=manifest)
        check_transition(None if previous is None else previous["state"], event, event["event_number"])
        check_artifacts(event, artifacts)
        identity = event_identity(run, event)
        event.update(event_hash=digest(identity), metadata_ciphertext=encrypt(canonical(identity), {"kind": "event", "identity": identity}, ring))
        connection.execute(insert(EVENT).values(**event))
        for kind, raw in encoded.items():
            for position in range(manifest[kind]["chunks"]):
                check_deadline(deadline)
                chunk = raw[position * CHUNK_BYTES:(position + 1) * CHUNK_BYTES]
                connection.execute(insert(CHUNK).values(event_id=event["id"], kind=kind, position=position,
                    ciphertext=encrypt(chunk, {"kind": kind, "position": position, "event": identity}, ring)))
        connection.execute(update(HEAD).where(HEAD.c.integration_id == run["integration_id"]).values(event_sequence=event["journal_sequence"]))
        return event

    def accept(self, integration_id, actor: HistoryActor, request, schema):
        deadline = time.monotonic() + self.limits.timeout_seconds
        actor.refresh()
        ticket = RunTicket(uuid4().hex, secrets.token_hex(32))
        with self.connection(write=True, actor=actor) as connection:
            head = self._head(connection, integration_id)
            actor.refresh()  # Fresh after waiting for another writer.
            run = dict(id=ticket.run_id, integration_id=integration_id, run_sequence=head["run_sequence"] + 1,
                actor_id=actor.actor_id, origin=actor.origin, scope_kind="installation", created_at=now())
            identity = run_identity(run)
            metadata = {"identity": identity, "ticket_hash": hashlib.sha256(ticket.token.encode()).hexdigest(), "policy_version": 1}
            if len(canonical(metadata)) > self.limits.artifact_bytes:
                raise HistoryError("HISTORY_BUDGET_EXCEEDED", 413)
            run["metadata_ciphertext"] = encrypt(canonical(metadata), {"kind": "run", "identity": identity}, self.ring())
            connection.execute(insert(RUN).values(**run))
            self._append(connection, run, head, "accepted", {"request": request, "schema": schema}, deadline=deadline)
            connection.execute(update(HEAD).where(HEAD.c.integration_id == integration_id).values(run_sequence=run["run_sequence"], active_runs=head["active_runs"] + 1))
        return ticket

    def append(self, ticket: RunTicket, state, artifacts=None, *, actor=None):
        deadline = time.monotonic() + self.limits.timeout_seconds
        with self.connection(write=True, actor=actor) as connection:
            run = connection.execute(select(*bounded_projection(RUN, self.limits)).where(RUN.c.id == ticket.run_id)).mappings().first()
            if run is None:
                raise HistoryError("HISTORY_NOT_FOUND", 404)
            check_row(run, RUN)
            head = self._head(connection, run["integration_id"])
            metadata = checked_json(decrypt(run["metadata_ciphertext"], {"kind": "run", "identity": run_identity(run)}, self.ring()))
            if not isinstance(metadata, dict) or not isinstance(metadata.get("ticket_hash"), str):
                raise HistoryError("HISTORY_CORRUPT")
            if not hmac.compare_digest(metadata["ticket_hash"], hashlib.sha256(ticket.token.encode()).hexdigest()):
                raise HistoryError("HISTORY_FORBIDDEN", 403)
            if actor is not None:
                actor.refresh()
                if actor.actor_id != run["actor_id"]:
                    raise HistoryError("HISTORY_FORBIDDEN", 403)
            events = self._events(connection, run, deadline=deadline)
            previous = events[-1][0]
            if previous["state"] in TERMINAL or (state == "execution_started" and previous["state"] != "accepted") or (state == "completed" and previous["state"] != "execution_started") or state not in TERMINAL | {"execution_started"}:
                raise HistoryError("HISTORY_BUSY", 409)
            return self._append(connection, run, head, state, artifacts or {}, previous, deadline=deadline)

    def _events(self, connection, run, upper=None, *, deadline=None):
        check_row(run, RUN)
        identity = run_identity(run)
        metadata = checked_json(decrypt(run["metadata_ciphertext"], {"kind": "run", "identity": identity}, self.ring()))
        if not isinstance(metadata, dict) or metadata.get("identity") != identity:
            raise HistoryError("HISTORY_CORRUPT")
        statement = select(*bounded_projection(EVENT, self.limits)).where(EVENT.c.run_id == run["id"]).order_by(EVENT.c.event_number).limit(4)
        if upper is not None:
            statement = statement.where(EVENT.c.journal_sequence <= upper)
        result: list[tuple[Any, dict]] = []
        previous = ""
        for event in connection.execute(statement).mappings():
            check_row(event, EVENT)
            if event["event_number"] != len(result) + 1 or event["previous_hash"] != previous or (not result and event["state"] != "accepted") or (result and result[-1][0]["state"] in TERMINAL):
                raise HistoryError("HISTORY_CORRUPT")
            check_transition(None if not result else result[-1][0]["state"], event, len(result) + 1)
            artifacts = verified_artifacts(connection, run, event, self.ring(), self.limits, deadline=deadline)
            check_artifacts(event, artifacts)
            result.append((event, artifacts))
            previous = event["event_hash"]
        if not result:
            raise HistoryError("HISTORY_CORRUPT")
        return result

    def _record(self, connection, run, upper=None, projection="full", *, deadline=None):
        events = self._events(connection, run, upper, deadline=deadline)
        last, artifacts = events[-1]
        outcome = artifacts.get("response", {"success": False, "message": "Ergebnis noch nicht bestätigt.", "details": {"status": "outcome_unconfirmed", "retry_automatically": False}})
        request = events[0][1]["request"]
        record = {"id": run["id"], "integration_id": run["integration_id"], "success": outcome["success"], "message": outcome.get("message", ""),
            "payload": request.get("payload", {}) if projection == "full" else {}, "details": outcome.get("details") if projection == "full" else None,
            "created_at": stamp(run["created_at"]), "actor_id": run["actor_id"], "origin": run["origin"], "scope_kind": run["scope_kind"],
            "history_status": "outcome_unconfirmed" if last["state"] in {"accepted", "execution_started"} else last["state"], "policy_version": 1}
        return record, events

    def page(self, integration_id, actor, *, limit=20, cursor=None, state=None, projection="full"):
        deadline = time.monotonic() + self.limits.timeout_seconds
        actor.refresh()
        if type(limit) is not int or limit < 1 or projection not in {"full", "summary"} or state not in {None, "completed", "rejected", "outcome_uncertain", "observation_failed", "pending"}:
            raise HistoryError("HISTORY_CURSOR_INVALID", 400)
        binding = {"kind": "cursor", "integration_id": integration_id, "actor": actor.fingerprint()}
        with self.connection() as connection:
            head = connection.execute(select(HEAD).where(HEAD.c.integration_id == integration_id)).mappings().first()
            if head is None:
                return {"items": [], "next_cursor": None, "has_more": False, "history_started_at": None, "projection": projection}
            snapshot = {"upper_run": head["run_sequence"], "upper_event": head["event_sequence"], "after": head["run_sequence"] + 1,
                "epoch": head["clear_epoch"], "state": state, "projection": projection, "limit": limit}
            if cursor:
                try:
                    supplied = checked_json(decrypt(cursor, binding, self.ring()))
                    if set(supplied) != set(snapshot) or any(supplied[key] != snapshot[key] for key in ("epoch", "state", "projection", "limit")) or any(type(supplied[key]) is not int or supplied[key] < 0 for key in ("upper_run", "upper_event", "after")):
                        raise ValueError()
                    snapshot = supplied
                except (HistoryError, ValueError, TypeError):
                    raise HistoryError("HISTORY_CURSOR_INVALID", 409) from None
            latest = select(func.max(EVENT.c.journal_sequence)).where(EVENT.c.run_id == RUN.c.id, EVENT.c.journal_sequence <= snapshot["upper_event"]).correlate(RUN).scalar_subquery()
            statement = select(*bounded_projection(RUN, self.limits)).join(EVENT, and_(EVENT.c.run_id == RUN.c.id, EVENT.c.journal_sequence == latest)).where(RUN.c.integration_id == integration_id,
                RUN.c.run_sequence <= snapshot["upper_run"], RUN.c.run_sequence < snapshot["after"]).order_by(RUN.c.run_sequence.desc()).limit(limit + 1)
            if state is not None:
                statement = statement.where(EVENT.c.state.in_(["accepted", "execution_started"]) if state == "pending" else EVENT.c.state == state)
            selected = connection.execute(statement).mappings().all()
            items, size = [], 0
            for run in selected[:limit]:
                check_deadline(deadline)
                record, _ = self._record(connection, run, snapshot["upper_event"], projection, deadline=deadline)
                size += len(canonical(record))
                if size > self.limits.page_bytes:
                    raise HistoryError("HISTORY_BUDGET_EXCEEDED", 413)
                items.append(record)
            actor.refresh()
            if connection.scalar(select(HEAD.c.clear_epoch).where(HEAD.c.integration_id == integration_id)) != snapshot["epoch"]:
                raise HistoryError("HISTORY_CURSOR_INVALID", 409)
            more = len(selected) > limit
            if more:
                snapshot["after"] = selected[limit - 1]["run_sequence"]
            return {"items": items, "next_cursor": encrypt(canonical(snapshot), binding, self.ring()) if more else None,
                "has_more": more, "history_started_at": stamp(head["history_started_at"]), "history_complete_from": stamp(head["history_started_at"]), "projection": projection}

    def detail(self, integration_id, run_id, actor):
        deadline = time.monotonic() + self.limits.timeout_seconds
        actor.refresh()
        with self.connection() as connection:
            run = connection.execute(select(*bounded_projection(RUN, self.limits)).where(RUN.c.id == run_id, RUN.c.integration_id == integration_id)).mappings().first()
            if run is None:
                raise HistoryError("HISTORY_NOT_FOUND", 404)
            record, events = self._record(connection, run, deadline=deadline)
            record["observations"] = [{"state": event["state"], "event_number": event["event_number"], "created_at": stamp(event["created_at"]), "event_hash": event["event_hash"], "artifacts": artifacts} for event, artifacts in events]
            if len(canonical(record)) > self.limits.page_bytes:
                raise HistoryError("HISTORY_BUDGET_EXCEEDED", 413)
            actor.refresh()
            return record

    def clear(self, integration_id, actor):
        deadline = time.monotonic() + self.limits.timeout_seconds
        actor.refresh()
        with self.connection(write=True, actor=actor) as connection:
            head = self._head(connection, integration_id)
            actor.refresh()
            latest = select(func.max(EVENT.c.event_number)).where(EVENT.c.run_id == RUN.c.id).correlate(RUN).scalar_subquery()
            if connection.execute(select(RUN.c.id).join(EVENT, and_(EVENT.c.run_id == RUN.c.id, EVENT.c.event_number == latest)).where(RUN.c.integration_id == integration_id, EVENT.c.state.in_(["accepted", "execution_started"])).limit(1)).first():
                raise HistoryError("HISTORY_BUSY", 409)
            count, event_count, checksum = 0, 0, hashlib.sha256()
            # Every candidate is verified before the first DELETE; bounded
            # server-side transfer rather than collecting all IDs/history.
            result = connection.execution_options(stream_results=True).execute(select(*bounded_projection(RUN, self.limits)).where(RUN.c.integration_id == integration_id).order_by(RUN.c.run_sequence))
            try:
                for run in result.mappings():
                    check_deadline(deadline)
                    record, events = self._record(connection, run, deadline=deadline)
                    checksum.update(canonical(record))
                    count += 1
                    event_count += len(events)
            finally:
                result.close()
                connection.execution_options(stream_results=False)
            clear = dict(id=uuid4().hex, integration_id=integration_id, clear_epoch=head["clear_epoch"] + 1, actor_id=actor.actor_id, created_at=now(), cleared=count)
            identity = {key: stamp(value) if key == "created_at" else value for key, value in clear.items()}
            proof = {"identity": identity, "event_count": event_count, "manifest_sha256": checksum.hexdigest()}
            clear["metadata_ciphertext"] = encrypt(canonical(proof), {"kind": "clear", "identity": identity}, self.ring())
            actor.refresh()
            connection.execute(insert(CLEAR).values(**clear))
            run_ids = select(RUN.c.id).where(RUN.c.integration_id == integration_id)
            event_ids = select(EVENT.c.id).where(EVENT.c.run_id.in_(run_ids))
            connection.execute(delete(CHUNK).where(CHUNK.c.event_id.in_(event_ids)))
            connection.execute(delete(EVENT).where(EVENT.c.run_id.in_(run_ids)))
            connection.execute(delete(RUN).where(RUN.c.integration_id == integration_id))
            connection.execute(update(HEAD).where(HEAD.c.integration_id == integration_id).values(active_runs=0, clear_epoch=clear["clear_epoch"]))
            return {"id": integration_id, "cleared": count}

    def metrics(self, integration_ids, actor):
        actor.refresh()
        counts = {"runs_total": 0, "runs_successful": 0, "runs_pending": 0, "runs_uncertain": 0}
        with self.connection() as connection:
            # Fixed, small state projection; never deserialize all run payloads.
            latest = select(func.max(EVENT.c.event_number)).where(EVENT.c.run_id == RUN.c.id).correlate(RUN).scalar_subquery()
            query = select(EVENT.c.state, EVENT.c.success, func.count()).select_from(RUN.join(EVENT, and_(EVENT.c.run_id == RUN.c.id, EVENT.c.event_number == latest))).where(RUN.c.integration_id.in_(integration_ids)).group_by(EVENT.c.state, EVENT.c.success)
            for state, successful, count in connection.execute(query):
                counts["runs_total"] += count
                if successful is True:
                    counts["runs_successful"] += count
                if state in {"accepted", "execution_started"}:
                    counts["runs_pending"] += count
                elif state in {"outcome_uncertain", "observation_failed"}:
                    counts["runs_uncertain"] += count
            actor.refresh()
        counts["runs_failed"] = counts["runs_total"] - counts["runs_successful"]
        return counts


_configured_store = None


def configure_history(session_factory, *, limits=None):
    global _configured_store
    _configured_store = SQLIntegrationHistoryStore(session_factory, limits=limits)
    return _configured_store


def configured_history():
    if _configured_store is None:
        raise HistoryError("HISTORY_NOT_CONFIGURED")
    return _configured_store


def lock_history_fence(connection, *, nowait=False):
    """Caller-owned transaction; acquire after Account and Domain locks.

    PostgreSQL barrier prevents INSERT/UPDATE/DELETE on every journal table.
    SQLite caller must already own BEGIN IMMEDIATE; the independent wrapper
    below supplies that when Memory-domain reset uses the shared SQL journal.
    No commit, no key lookup, no provider callback.
    """
    if not ensure_history_schema(connection):
        return False
    if connection.dialect.name == "postgresql":
        from ...db.integration_history_models import TABLES

        connection.exec_driver_sql("LOCK TABLE " + ", ".join(TABLES) + " IN SHARE ROW EXCLUSIVE MODE" + (" NOWAIT" if nowait else ""))
    return True


@contextmanager
def history_fence(*, nowait=False):
    """Hold the actual configured journal connection throughout a Memory reset."""
    with configured_history().connection(write=True, passthrough_body=True) as connection:
        lock_history_fence(connection, nowait=nowait)
        yield connection
