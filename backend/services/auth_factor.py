"""Account-bound OTP attempts, shared by login and factor administration.

The existing transactional authentication quota table holds attempt times, never
codes or secrets. SQL workers serialize the same account's quota row.
"""

import base64
import hashlib
import logging
import threading
from time import time as _now
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from ..db.access_models import RegistrationQuotaORM

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60
_memory: dict[str, list[float]] = {}
_used: dict[str, int] = {}
_lock = threading.RLock()


def _key(user_id: str) -> str:
    return hashlib.sha256(("auth-totp-attempts-v1:" + user_id).encode()).hexdigest()


def _unavailable() -> HTTPException:
    return HTTPException(503, "Die Zwei-Faktor-Prüfung ist vorübergehend nicht verfügbar. Bitte erneut versuchen.",
                         headers={"Retry-After": "30"})


class FactorReplay(Exception):
    """A verified code's step has already been consumed for this account/key."""


def _rollback(session) -> None:
    if session is not None:
        try:
            session.rollback()
        except SQLAlchemyError:
            pass


def _close(session) -> None:
    if session is not None:
        try:
            session.close()
        except SQLAlchemyError:
            # A close failure cannot undo a confirmed commit; expose no SQL.
            logger.warning("Authentication factor quota cleanup failed")


def reserve(user_id: str) -> None:
    """Reserve before checking a code; unavailable storage never permits a guess."""
    from .. import auth

    now = _now()
    key = _key(user_id)
    if auth._auth_session_factory is None:
        with _lock:
            recent = [stamp for stamp in _memory.get(key, []) if stamp > now - WINDOW_SECONDS]
            blocked = len(recent) >= MAX_ATTEMPTS
            if not blocked:
                recent.append(now)
            _memory[key] = recent
    else:
        session = None
        try:
            session = auth._new_auth_session()
            dialect = session.get_bind().dialect.name
            insert: Any
            if dialect == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
                insert = sqlite_insert(RegistrationQuotaORM)
            elif dialect == "postgresql":
                insert = pg_insert(RegistrationQuotaORM)
            else:
                raise RuntimeError("Unsupported authentication quota database")
            session.execute(insert.values(key_hash=key, attempts=[]).on_conflict_do_nothing(index_elements=["key_hash"]))
            row = session.execute(select(RegistrationQuotaORM).where(
                RegistrationQuotaORM.key_hash == key).with_for_update()).scalar_one()
            recent = [stamp for stamp in row.attempts if stamp > now - WINDOW_SECONDS]
            blocked = len(recent) >= MAX_ATTEMPTS
            if not blocked:
                recent.append(now)
            row.attempts = recent
            session.commit()
        except (SQLAlchemyError, RuntimeError, TypeError, ValueError):
            _rollback(session)
            logger.warning("Authentication factor quota unavailable; attempt refused")
            raise _unavailable() from None
        finally:
            _close(session)
    if blocked:
        raise HTTPException(429, "Zu viele falsche Zwei-Faktor-Codes. Bitte warten Sie 15 Minuten.",
                            headers={"Retry-After": str(WINDOW_SECONDS)})


def complete(user_id: str, *, secret: str, counter: int) -> None:
    """Atomically consume a verified step and reset attempts before tokens issue.

    A high-water step, shared across login/activation/disabling, refuses replays
    through the accepted previous/current/next windows. Secret rotation has its
    own non-reversible identity. Neither the secret nor the code is persisted.
    """
    from .. import auth

    if type(counter) is not int or counter < 0:
        raise ValueError("Invalid verified factor step")
    key = _key(user_id)
    identity = hashlib.sha256(base64.b32decode(secret, casefold=True)).hexdigest()
    used_key = hashlib.sha256(("auth-totp-used-v1:" + user_id + ":" + identity).encode()).hexdigest()
    if auth._auth_session_factory is None:
        with _lock:
            if counter <= _used.get(used_key, -1):
                raise FactorReplay()
            _used[used_key] = counter
            _memory.pop(key, None)
        return
    session = None
    try:
        session = auth._new_auth_session()
        dialect = session.get_bind().dialect.name
        insert: Any
        if dialect == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
            insert = sqlite_insert(RegistrationQuotaORM)
        elif dialect == "postgresql":
            insert = pg_insert(RegistrationQuotaORM)
        else:
            raise RuntimeError("Unsupported authentication quota database")
        session.execute(insert.values(key_hash=used_key, attempts=[]).on_conflict_do_nothing(index_elements=["key_hash"]))
        row = session.execute(select(RegistrationQuotaORM).where(
            RegistrationQuotaORM.key_hash == used_key).with_for_update()).scalar_one()
        previous = row.attempts
        if (len(previous) > 1 or previous and (type(previous[0]) is not int or previous[0] < 0)):
            raise ValueError("Invalid factor step journal")
        if previous and counter <= previous[0]:
            raise FactorReplay()
        row.attempts = [counter]
        session.execute(delete(RegistrationQuotaORM).where(RegistrationQuotaORM.key_hash == key))
        session.commit()
    except FactorReplay:
        _rollback(session)
        raise
    except (SQLAlchemyError, RuntimeError, ValueError, TypeError):
        _rollback(session)
        logger.warning("Authentication factor quota reset unavailable; completion refused")
        raise _unavailable() from None
    finally:
        _close(session)


def clear_memory() -> None:
    """Test/store-reset boundary; ordinary logins clear only their own account."""
    with _lock:
        _memory.clear()
        _used.clear()
