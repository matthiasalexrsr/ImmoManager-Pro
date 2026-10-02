"""Authoritative account sessions. Token values never enter durable storage."""

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth
from ..db.orm_models import UserORM
from ..db.session_models import AuthRefreshORM, AuthSessionORM
from ..models import TokenPayload, TokenResponse

VERSION = 1


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fingerprint(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def device_label(user_agent):
    """An untrusted label, not a device identity: never persist raw UA or IP."""
    value = (user_agent or "")[:1024].lower()
    browser = next((label for marker, label in (("edg/", "Edge"), ("firefox/", "Firefox"),
        ("chrome/", "Chrome"), ("safari/", "Safari")) if marker in value), "Browser")
    platform = next((label for marker, label in (("android", "Android"), ("iphone", "iOS"),
        ("ipad", "iOS"), ("windows", "Windows"), ("macintosh", "macOS"), ("linux", "Linux"))
        if marker in value), "Unknown")
    return browser + " / " + platform


def denied():
    return HTTPException(401, "Sitzung abgelaufen oder widerrufen. Bitte erneut anmelden.", headers={"WWW-Authenticate": "Bearer"})


def factory():
    # Auth state belongs to the factory that authenticated the account, never
    # the business store, default database URL, or a newly created fallback DB.
    if auth._auth_session_factory is not None:
        return auth._auth_session_factory
    if isinstance(auth._user_store, auth.SQLUserStore):
        return auth._user_store._session_factory
    return None


@contextmanager
def transaction(*, write=False):
    selected = factory()
    if selected is None:
        if not isinstance(auth._user_store, auth.InMemoryUserStore):
            raise HTTPException(503, "Sitzungsverwaltung ist derzeit nicht verfügbar.")
        with auth._user_store._lock:
            auth._user_store.__dict__.setdefault("_auth_sessions", {})
            auth._user_store.__dict__.setdefault("_auth_refresh_tokens", {})
            yield None
        return
    db = None
    try:
        db = selected()
        if not isinstance(db, Session):
            raise RuntimeError("Unsupported authentication session")
        if write and db.get_bind().dialect.name == "sqlite":
            # A SELECT followed by UPDATE is not a serialization boundary in
            # sqlite3 legacy/WAL mode. Acquire the writer before reading.
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield db
        if write:
            db.commit()
        else:
            db.rollback()
    except HTTPException:
        if db is not None:
            db.rollback()
        raise
    except Exception:
        if db is not None:
            db.rollback()
        raise HTTPException(503, "Sitzungsverwaltung ist derzeit nicht verfügbar.") from None
    finally:
        if db is not None:
            db.close()


def family(db, identifier, *, lock=False):
    if db is None:
        return auth._user_store.__dict__["_auth_sessions"].get(identifier)
    query = select(AuthSessionORM).where(AuthSessionORM.id == identifier)
    return db.scalar(query.with_for_update() if lock else query)


def receipt(db, token_hash):
    if db is None:
        return auth._user_store.__dict__["_auth_refresh_tokens"].get(token_hash)
    return db.get(AuthRefreshORM, token_hash)


def legacy_family(db, token_hash):
    if db is None:
        return next((row for row in auth._user_store.__dict__["_auth_sessions"].values()
                     if row.legacy_refresh_hash == token_hash), None)
    return db.scalar(select(AuthSessionORM).where(AuthSessionORM.legacy_refresh_hash == token_hash).with_for_update())


def active_user(db, identifier):
    if db is None:
        user = auth.get_user_by_id(identifier)
        return bool(user and user["is_active"])
    user = db.scalar(select(UserORM).where(UserORM.id == identifier).with_for_update())
    return bool(user and user.is_active)


def alive(row):
    return row is not None and row.revoked_at is None and row.expires_at > now()


def revoke(row, reason):
    if row.revoked_at is None:
        row.revoked_at, row.revoke_reason = now(), reason


def token_pair(row):
    issued = now().replace(tzinfo=timezone.utc)
    expires = row.expires_at.replace(tzinfo=timezone.utc)
    common = {"sub": row.user_id, "sid": row.id, "session_version": VERSION, "iat": issued}
    access = jwt.encode({**common, "exp": min(expires, issued + timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)),
        "type": "access", "jti": str(uuid4())}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    refresh = jwt.encode({**common, "exp": expires, "type": "refresh", "jti": str(uuid4())},
        auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    return TokenResponse(access_token=access, refresh_token=refresh)


def add_receipt(db, row, tokens):
    row.current_refresh_hash = fingerprint(tokens.refresh_token)
    record = AuthRefreshORM(token_hash=row.current_refresh_hash, session_id=row.id, generation=row.generation,
        expires_at=row.expires_at, consumed_at=None)
    if db is None:
        auth._user_store.__dict__["_auth_refresh_tokens"][record.token_hash] = record
    else:
        db.add(record)


def new_family(db, user_id, user_agent, *, expires=None, legacy=None):
    created = now()
    row = AuthSessionORM(id=str(uuid4()), user_id=user_id, device_label=device_label(user_agent),
        created_at=created, last_used_at=created, expires_at=expires or created + timedelta(days=auth.REFRESH_TOKEN_EXPIRE_DAYS),
        revoked_at=None, revoke_reason=None, generation=0, current_refresh_hash="", legacy_refresh_hash=legacy)
    if db is None:
        auth._user_store.__dict__["_auth_sessions"][row.id] = row
    else:
        db.add(row)
        db.flush()  # The consumed/new refresh row FK requires the family first.
    return row


def login_pair(user_id, user_agent=None):
    with transaction(write=True) as db:
        if not active_user(db, user_id):
            raise denied()
        row = new_family(db, user_id, user_agent)
        tokens = token_pair(row)
        add_receipt(db, row, tokens)
    return tokens


def rotate(token, user_agent=None):
    # Signature, expiry and token type are validated, but consumed fingerprints
    # must remain readable here: rejecting them earlier hides family replay.
    claims = auth.decode_signed_token(token)
    if claims.type != "refresh":
        raise denied()
    token_hash = fingerprint(token)
    failure = False
    tokens = None
    with transaction(write=True) as db:
        # The user row serializes first-time legacy adoption and owner changes
        # as well; PostgreSQL family locks serialize subsequent rotations.
        if not active_user(db, claims.sub):
            raise denied()
        if claims.sid is None:
            row = legacy_family(db, token_hash)
            if row is not None:
                revoke(row, "refresh_reuse")
                failure = True
            elif auth.is_token_revoked(token):
                raise denied()
            else:
                row = new_family(db, claims.sub, user_agent,
                    expires=claims.exp.astimezone(timezone.utc).replace(tzinfo=None), legacy=token_hash)
                previous = AuthRefreshORM(token_hash=token_hash, session_id=row.id, generation=-1,
                    expires_at=row.expires_at, consumed_at=now())
                if db is None:
                    auth._user_store.__dict__["_auth_refresh_tokens"][token_hash] = previous
                else:
                    db.add(previous)
        else:
            row = family(db, claims.sid, lock=True)
            previous = receipt(db, token_hash)
            if row is None or row.user_id != claims.sub or previous is None or previous.session_id != row.id:
                raise denied()
            if not alive(row):
                raise denied()
            if previous.consumed_at is not None or row.current_refresh_hash != token_hash:
                revoke(row, "refresh_reuse")
                failure = True
            else:
                previous.consumed_at = now()
                row.generation += 1
                row.last_used_at = now()
        if not failure:
            tokens = token_pair(row)
            add_receipt(db, row, tokens)
    # Commit the security response before returning 401. An HTTP exception
    # inside the transaction would roll back the family-wide replay revocation.
    if failure or tokens is None:
        raise denied()
    return tokens


def token_revoked(claims: TokenPayload, token: str):
    if claims.sid is None:
        return False
    with transaction() as db:
        row = family(db, claims.sid)
        if not alive(row) or row.user_id != claims.sub:
            return True
        if claims.type == "refresh":
            previous = receipt(db, fingerprint(token))
            return previous is None or previous.session_id != row.id or previous.consumed_at is not None
    return False


def touch(claims):
    if claims.sid is None or claims.type != "access":
        return
    with transaction() as db:
        row = family(db, claims.sid)
        needed = alive(row) and row.last_used_at < now() - timedelta(minutes=1)
    if needed:
        with transaction(write=True) as db:
            row = family(db, claims.sid, lock=True)
            if not alive(row) or row.user_id != claims.sub:
                raise denied()
            row.last_used_at = max(row.last_used_at, now())


def revoke_from_token(token, reason="logout"):
    try:
        claims = auth.decode_signed_token(token)
    except HTTPException as error:
        if error.status_code == 401:
            return
        raise
    if claims.sid is None:
        return
    with transaction(write=True) as db:
        row = family(db, claims.sid, lock=True)
        if row is not None and row.user_id == claims.sub:
            revoke(row, reason)


def public(row, current_id):
    return {"id": row.id, "device_label": row.device_label, "current": row.id == current_id,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "last_used_at": row.last_used_at.replace(tzinfo=timezone.utc).isoformat(),
        "expires_at": row.expires_at.replace(tzinfo=timezone.utc).isoformat(),
        "revoked_at": row.revoked_at.replace(tzinfo=timezone.utc).isoformat() if row.revoked_at else None,
        "revoke_reason": row.revoke_reason, "status": "active" if alive(row) else "revoked" if row.revoked_at else "expired"}


def list_sessions(user_id, current_id, offset=0, limit=25):
    with transaction() as db:
        if db is None:
            rows = sorted((row for row in auth._user_store.__dict__["_auth_sessions"].values()
                           if row.user_id == user_id), key=lambda row: (row.created_at, row.id), reverse=True)
            total = len(rows)
            items = rows[offset:offset + limit]
        else:
            condition = AuthSessionORM.user_id == user_id
            total = db.scalar(select(func.count()).select_from(AuthSessionORM).where(condition))
            items = db.scalars(select(AuthSessionORM).where(condition)
                .order_by(AuthSessionORM.created_at.desc(), AuthSessionORM.id.desc()).offset(offset).limit(limit)).all()
        return {"items": [public(row, current_id) for row in items], "total": total,
            "offset": offset, "limit": limit, "current_session_id": current_id,
            "legacy_current": current_id is None, "persistent": factory() is not None}


def revoke_own(user_id, identifier, current_id):
    with transaction(write=True) as db:
        row = family(db, identifier, lock=True)
        if row is None or row.user_id != user_id:
            raise HTTPException(404, "Sitzung nicht gefunden")
        revoke(row, "user_revoke")
        result = public(row, current_id)
    return result
