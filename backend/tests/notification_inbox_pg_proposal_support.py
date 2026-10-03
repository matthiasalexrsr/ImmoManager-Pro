"""Owned disposable M2 PG fixture support; no application/settings imports."""

import math
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.pool import QueuePool

NODE_SECONDS = 30.0
CLEANUP_SECONDS = 8.0
_SCHEMA = re.compile(r"notification_inbox_m2_[0-9a-f]{32}\Z")


def dedicated_url(source: str | URL | None) -> URL:
    """Refuse target-changing URL parameters before engine/DBAPI construction."""
    try:
        url = make_url(source) if source else None
        if (url is None or url.drivername not in {"postgresql", "postgresql+psycopg2"}
                or url.host not in {"localhost", "127.0.0.1"}
                or url.port not in {58112, 5432} or url.database != "immo_ci"
                or url.username != "immo_ci" or url.query):
            raise ValueError
        return URL.create("postgresql+psycopg2", username="immo_ci", password=url.password,
                          host="127.0.0.1", port=url.port, database="immo_ci")
    except Exception:
        raise ValueError("notification_inbox_pg_target_invalid") from None


def remaining(deadline: float) -> float:
    if not math.isfinite(deadline):
        raise ValueError("notification_inbox_pg_deadline_invalid")
    value = deadline - monotonic()
    if value <= 0:
        raise TimeoutError("notification_inbox_pg_node_timeout")
    return value


def _schema_name(schema: str) -> str:
    if schema != "pg_catalog" and not _SCHEMA.fullmatch(schema):
        raise ValueError("notification_inbox_pg_schema_invalid")
    return schema


def _timeouts(deadline: float) -> tuple[int, int, int]:
    left = remaining(deadline)
    milliseconds = max(1, math.floor(left * 1000))
    return max(1, min(3, math.ceil(left))), min(5000, milliseconds), min(1500, milliseconds)


@dataclass
class _OwnedEngine:
    engine: Engine
    handles: list = field(default_factory=list)


def _engine(source: str | URL, schema: str, deadline: float) -> _OwnedEngine:
    url = dedicated_url(source)
    schema = _schema_name(schema)
    remaining(deadline)
    engine = create_engine(url, hide_parameters=True, poolclass=QueuePool,
                           pool_size=1, max_overflow=0, pool_timeout=min(2, remaining(deadline)))
    owned = _OwnedEngine(engine)

    @event.listens_for(engine, "do_connect")
    def connect(dialect, record, arguments, parameters):
        actual = dedicated_url(url)  # Revalidate before EVERY actual DBAPI connect.
        connect_seconds, sql_ms, lock_ms = _timeouts(deadline)
        parameters.update({
            "host": "127.0.0.1", "hostaddr": "127.0.0.1", "port": actual.port,
            "dbname": "immo_ci", "user": "immo_ci", "connect_timeout": connect_seconds,
            "options": (f"-csearch_path={schema} -ctimezone=UTC "
                        f"-cstatement_timeout={sql_ms} -clock_timeout={lock_ms} "
                        "-cidle_in_transaction_session_timeout=5000"),
        })
        handle = dialect.loaded_dbapi.connect(*arguments, **parameters)
        # Track the exact owned native handle even if dialect initialization fails.
        owned.handles.append(handle)
        try:
            remaining(deadline)
            cursor = handle.cursor()
            try:
                cursor.execute("SELECT current_database(),current_user,pg_catalog.host(pg_catalog.inet_server_addr()),"
                               "inet_server_port(),current_schema()")
                row = cursor.fetchone()
                if row != ("immo_ci", "immo_ci", "127.0.0.1", actual.port, schema):
                    raise ValueError("notification_inbox_pg_native_target_invalid")
                remaining(deadline)
            finally:
                cursor.close()
            handle.rollback()  # Only the fixture-owned inspection transaction.
            return handle
        except BaseException:
            handle.close()
            raise

    @event.listens_for(engine, "checkout")
    def checkout(handle, record, proxy):
        remaining(deadline)

    @event.listens_for(engine, "before_cursor_execute")
    def before_sql(connection, cursor, statement, parameters, context, executemany):
        _, sql_ms, lock_ms = _timeouts(deadline)
        # Bound each statement to its current remaining budget. These settings
        # touch only the disposable fixture connection, never a schema validator.
        # A streaming statement may own a named cursor which cannot execute
        # twice. Preserve it and close our independent settings cursor.
        settings_cursor = cursor.connection.cursor()
        try:
            settings_cursor.execute("SELECT pg_catalog.set_config('statement_timeout',%s,false)", (str(sql_ms),))
            remaining(deadline)
            settings_cursor.execute("SELECT pg_catalog.set_config('lock_timeout',%s,false)", (str(lock_ms),))
            remaining(deadline)
        finally:
            settings_cursor.close()

    @event.listens_for(engine, "after_cursor_execute")
    def after_sql(connection, cursor, statement, parameters, context, executemany):
        remaining(deadline)

    return owned


def _close(owned: _OwnedEngine, failures: list[str]) -> None:
    try:
        if owned.engine.pool.checkedout():
            failures.append("checkedout")
    except Exception:
        failures.append("pool_inspection_failed")
    try:
        owned.engine.dispose(close=True)
    except Exception:
        failures.append("dispose_failed")
    finally:
        # dispose alone does not close checked-out connections. These are actual
        # handles created and recorded by this fixture, never guessed processes.
        for handle in owned.handles:
            try:
                handle.close()
            except Exception:
                failures.append("owned_handle_close_failed")


def _namespace(connection, schema):
    result = connection.execute(text("SELECT oid,nspowner FROM pg_catalog.pg_namespace WHERE nspname=:schema"),
                                {"schema": schema})
    try:
        row = result.one_or_none()
        return tuple(row) if row is not None else None
    finally:
        result.close()


@contextmanager
def postgres_proposal_database(source: str | URL | None):
    url = dedicated_url(source)
    schema = "notification_inbox_m2_" + uuid4().hex
    deadline = monotonic() + NODE_SECONDS
    engines: list[_OwnedEngine] = []
    identity = None
    try:
        admin = _engine(url, "pg_catalog", deadline)
        engines.append(admin)
        with admin.engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            identity = _namespace(connection, schema)
            if identity is None:
                raise ValueError("notification_inbox_pg_namespace_unproved")
        business = _engine(url, schema, deadline)
        engines.append(business)
        yield business.engine
        remaining(deadline)
    finally:
        failures: list[str] = []
        for owned in reversed(engines):
            _close(owned, failures)
        if identity is not None:
            cleanup = None
            try:
                cleanup = _engine(url, "pg_catalog", monotonic() + CLEANUP_SECONDS)
                with cleanup.engine.begin() as connection:
                    actual = _namespace(connection, schema)
                    if actual is not None:
                        if actual != identity:
                            raise ValueError("notification_inbox_pg_namespace_changed")
                        connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            except Exception:
                failures.append("schema_cleanup_failed")
            finally:
                if cleanup is not None:
                    _close(cleanup, failures)
        if failures:
            raise AssertionError("notification_inbox_pg_cleanup_failed:" + ",".join(sorted(set(failures))))
