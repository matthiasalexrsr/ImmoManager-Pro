"""Authentication module: password hashing, JWT tokens, and FastAPI dependencies.

Supports two user storage backends:
  - InMemoryUserStore (default, for tests)
  - SQLUserStore (when enable_sql_users() is called with a session)
"""

import hashlib
import hmac
import logging
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import settings
from .models import TokenPayload, UserRead

logger = logging.getLogger(__name__)

# Configuration from centralized settings
SECRET_KEY = settings.jwt_secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days

# T21: Password policy constants
MIN_PASSWORD_LENGTH = 8
REQUIRE_UPPERCASE = True
REQUIRE_LOWERCASE = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL = False

# T21: Login rate limiting
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
_login_attempts: dict[str, list[datetime]] = {}  # username -> list of failed attempt times

# HTTP Bearer scheme
security = HTTPBearer(auto_error=False)

# Token blacklist for logout/revocation
_token_blacklist: set[str] = set()
_blacklist_expiry: dict[str, datetime] = {}  # token -> expiry time for cleanup

# DB-backed session factory for auth security state (set by enable_sql_auth_state)
_auth_session_factory = None

# Number of PBKDF2 iterations (OWASP recommended minimum for SHA-256)
_PBKDF2_ITERATIONS = 600_000


def validate_password_strength(password: str) -> list[str]:
    """T21: Validate password meets policy requirements. Returns list of violations."""
    errors = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Mindestens {MIN_PASSWORD_LENGTH} Zeichen erforderlich")
    if REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
        errors.append("Mindestens ein Großbuchstabe erforderlich")
    if REQUIRE_LOWERCASE and not any(c.islower() for c in password):
        errors.append("Mindestens ein Kleinbuchstabe erforderlich")
    if REQUIRE_DIGIT and not any(c.isdigit() for c in password):
        errors.append("Mindestens eine Ziffer erforderlich")
    if REQUIRE_SPECIAL and not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        errors.append("Mindestens ein Sonderzeichen erforderlich")
    return errors


def check_login_rate_limit(username: str) -> bool:
    """T21: Check if login is rate-limited. Returns True if blocked."""
    if _auth_session_factory is not None:
        return _check_login_rate_limit_db(username)
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    attempts = _login_attempts.get(username, [])
    recent = [t for t in attempts if t > cutoff]
    _login_attempts[username] = recent
    return len(recent) >= MAX_LOGIN_ATTEMPTS


def _check_login_rate_limit_db(username: str) -> bool:
    """DB-backed rate limit check."""
    from .db.orm_models import LoginAttemptORM
    session = _auth_session_factory()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
        count = session.query(LoginAttemptORM).filter(
            LoginAttemptORM.username == username,
            LoginAttemptORM.success == False,  # noqa: E712
            LoginAttemptORM.attempted_at > cutoff,
        ).count()
        return count >= MAX_LOGIN_ATTEMPTS
    except Exception:
        logger.warning("DB rate-limit check failed, falling back to in-memory", exc_info=True)
        return len([t for t in _login_attempts.get(username, []) if t > cutoff]) >= MAX_LOGIN_ATTEMPTS
    finally:
        session.close()


def record_failed_login(username: str) -> None:
    """T21: Record a failed login attempt."""
    if _auth_session_factory is not None:
        _record_login_attempt_db(username, success=False)
    if username not in _login_attempts:
        _login_attempts[username] = []
    _login_attempts[username].append(datetime.utcnow())


def _record_login_attempt_db(username: str, *, success: bool) -> None:
    """Persist a login attempt to the database."""
    from .db.orm_models import LoginAttemptORM
    session = _auth_session_factory()
    try:
        session.add(LoginAttemptORM(username=username, success=success))
        session.commit()
    except Exception:
        session.rollback()
        logger.warning("Failed to persist login attempt", exc_info=True)
    finally:
        session.close()


def clear_login_attempts(username: str) -> None:
    """T21: Clear login attempts after successful login."""
    _login_attempts.pop(username, None)
    if _auth_session_factory is not None:
        _record_login_attempt_db(username, success=True)


# ---------------------------------------------------------------------------
# T10: TOTP Two-Factor Authentication
# ---------------------------------------------------------------------------


def generate_totp_secret() -> str:
    """Generate a new TOTP secret key (base32 encoded)."""
    import base64
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii")


def get_totp_uri(secret: str, username: str, issuer: str = "ImmoManager Pro") -> str:
    """Generate a TOTP URI for QR code generation."""
    from urllib.parse import quote
    return f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against the secret. Allows 1 period drift."""
    import hmac as _hmac
    import struct
    import time

    if not code or len(code) != 6 or not code.isdigit():
        return False

    import base64
    key = base64.b32decode(secret, casefold=True)
    now = int(time.time())

    for offset in [-1, 0, 1]:  # Allow ±30s drift
        counter = (now // 30) + offset
        msg = struct.pack(">Q", counter)
        h = _hmac.new(key, msg, "sha1").digest()
        o = h[-1] & 0x0F
        token = str((struct.unpack(">I", h[o:o+4])[0] & 0x7FFFFFFF) % 1000000).zfill(6)
        if _hmac.compare_digest(token, code):
            return True
    return False


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2:sha256:{_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its PBKDF2 hash."""
    try:
        header, salt, stored_hash = hashed_password.split("$")
        _, _, iterations_str = header.split(":")
        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac("sha256", plain_password.encode(), salt.encode(), iterations)
        return hmac.compare_digest(dk.hex(), stored_hash)
    except (ValueError, AttributeError):
        return False


def create_access_token(user_id: str) -> str:
    """Create a JWT access token with a unique jti."""
    expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = str(uuid4())
    payload = {"sub": user_id, "exp": expires, "type": "access", "jti": jti}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token with a unique jti for rotation tracking."""
    expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid4())
    payload = {"sub": user_id, "exp": expires, "type": "refresh", "jti": jti}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _token_jti(token: str) -> str:
    """Derive a short identifier from a token for DB storage."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def revoke_token(token: str) -> None:
    """Add a token to the blacklist (for logout)."""
    _cleanup_blacklist()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = datetime.utcfromtimestamp(payload["exp"])
        _token_blacklist.add(token)
        _blacklist_expiry[token] = exp
        # Also persist to DB for cross-restart durability
        if _auth_session_factory is not None:
            _revoke_token_db(token, exp)
    except JWTError:
        pass


def _revoke_token_db(token: str, expires_at: datetime) -> None:
    """Persist token revocation to the database."""
    from .db.orm_models import RevokedTokenORM
    session = _auth_session_factory()
    try:
        jti = _token_jti(token)
        exists = session.query(RevokedTokenORM).filter(
            RevokedTokenORM.token_jti == jti
        ).first()
        if not exists:
            session.add(RevokedTokenORM(token_jti=jti, expires_at=expires_at))
            session.commit()
    except Exception:
        session.rollback()
        logger.warning("Failed to persist token revocation to DB", exc_info=True)
    finally:
        session.close()


def is_token_revoked(token: str) -> bool:
    """Check if a token has been revoked."""
    if token in _token_blacklist:
        return True
    # Check DB if available
    if _auth_session_factory is not None:
        return _is_token_revoked_db(token)
    return False


def _is_token_revoked_db(token: str) -> bool:
    """Check DB for revoked token."""
    from .db.orm_models import RevokedTokenORM
    session = _auth_session_factory()
    try:
        jti = _token_jti(token)
        found = session.query(RevokedTokenORM).filter(
            RevokedTokenORM.token_jti == jti
        ).first()
        if found:
            # Cache in memory so subsequent checks are fast
            _token_blacklist.add(token)
            return True
        return False
    except Exception:
        logger.warning("DB token revocation check failed", exc_info=True)
        return False
    finally:
        session.close()


def _cleanup_blacklist() -> None:
    """Remove expired tokens from the blacklist."""
    now = datetime.utcnow()
    expired = [t for t, exp in _blacklist_expiry.items() if exp < now]
    for t in expired:
        _token_blacklist.discard(t)
        _blacklist_expiry.pop(t, None)
    # Clean expired DB entries periodically
    if _auth_session_factory is not None and expired:
        _cleanup_blacklist_db()


def _cleanup_blacklist_db() -> None:
    """Remove expired revoked tokens from the database."""
    from .db.orm_models import RevokedTokenORM
    session = _auth_session_factory()
    try:
        session.query(RevokedTokenORM).filter(
            RevokedTokenORM.expires_at < datetime.utcnow()
        ).delete()
        session.commit()
    except Exception:
        session.rollback()
        logger.debug("Failed to clean expired revoked tokens from DB", exc_info=True)
    finally:
        session.close()


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT token. Rejects revoked tokens."""
    if is_token_revoked(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token wurde widerrufen",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenPayload(**payload)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger Token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# User Store abstraction
# ---------------------------------------------------------------------------


class UserStore(ABC):
    """Abstract interface for user persistence."""

    @abstractmethod
    def get_by_id(self, user_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def get_by_username(self, username: str) -> Optional[dict]:
        ...

    @abstractmethod
    def create(self, user_data: dict) -> None:
        ...

    @abstractmethod
    def update(self, user_id: str, updates: dict) -> Optional[dict]:
        ...

    @abstractmethod
    def delete(self, user_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def list_all(self) -> list[dict]:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...


class InMemoryUserStore(UserStore):
    """In-memory user storage for tests and development."""

    def __init__(self):
        self._by_id: dict[str, dict] = {}
        self._by_username: dict[str, dict] = {}

    def get_by_id(self, user_id: str) -> Optional[dict]:
        return self._by_id.get(user_id)

    def get_by_username(self, username: str) -> Optional[dict]:
        return self._by_username.get(username)

    def create(self, user_data: dict) -> None:
        self._by_id[user_data["id"]] = user_data
        self._by_username[user_data["username"]] = user_data

    def update(self, user_id: str, updates: dict) -> Optional[dict]:
        user = self._by_id.get(user_id)
        if user is None:
            return None
        for key, value in updates.items():
            if value is not None and key not in ("id", "hashed_password", "created_at"):
                user[key] = value
        user["updated_at"] = datetime.utcnow()
        return user

    def delete(self, user_id: str) -> Optional[dict]:
        user = self._by_id.pop(user_id, None)
        if user:
            self._by_username.pop(user["username"], None)
        return user

    def list_all(self) -> list[dict]:
        return list(self._by_id.values())

    def clear(self) -> None:
        self._by_id.clear()
        self._by_username.clear()


class SQLUserStore(UserStore):
    """SQLAlchemy-backed user storage for production."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _finalize_session(self, session) -> None:
        """Return DB resources and clear scoped-session state when configured.

        For regular sessionmaker factories, session.close() is sufficient.
        For scoped_session factories, remove() must always run to clear thread-local
        identity; otherwise sessions can leak under concurrency and exhaust QueuePool.
        """
        remove = getattr(self._session_factory, "remove", None)
        if callable(remove):
            try:
                session.close()
            finally:
                remove()
            return

        session.close()

    def _to_dict(self, orm_obj) -> dict:
        return {
            "id": orm_obj.id,
            "username": orm_obj.username,
            "email": orm_obj.email,
            "full_name": orm_obj.full_name,
            "hashed_password": orm_obj.hashed_password,
            "role": orm_obj.role,
            "is_active": orm_obj.is_active,
            "totp_secret": orm_obj.totp_secret,
            "totp_enabled": orm_obj.totp_enabled,
            "created_at": orm_obj.created_at,
            "updated_at": orm_obj.updated_at,
        }

    def get_by_id(self, user_id: str) -> Optional[dict]:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            obj = session.get(UserORM, user_id)
            return self._to_dict(obj) if obj else None
        finally:
            self._finalize_session(session)

    def get_by_username(self, username: str) -> Optional[dict]:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            obj = session.query(UserORM).filter(UserORM.username == username).first()
            return self._to_dict(obj) if obj else None
        finally:
            self._finalize_session(session)

    def create(self, user_data: dict) -> None:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            obj = UserORM(**user_data)
            session.add(obj)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._finalize_session(session)

    def update(self, user_id: str, updates: dict) -> Optional[dict]:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            obj = session.get(UserORM, user_id)
            if obj is None:
                return None
            for key, value in updates.items():
                if value is not None and key not in ("id", "hashed_password", "created_at"):
                    setattr(obj, key, value)
            obj.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(obj)
            return self._to_dict(obj)
        except Exception:
            session.rollback()
            raise
        finally:
            self._finalize_session(session)

    def delete(self, user_id: str) -> Optional[dict]:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            obj = session.get(UserORM, user_id)
            if obj is None:
                return None
            data = self._to_dict(obj)
            session.delete(obj)
            session.commit()
            return data
        except Exception:
            session.rollback()
            raise
        finally:
            self._finalize_session(session)

    def list_all(self) -> list[dict]:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            return [self._to_dict(obj) for obj in session.query(UserORM).all()]
        finally:
            self._finalize_session(session)

    def clear(self) -> None:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            session.query(UserORM).delete()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._finalize_session(session)


# Default: in-memory store
_user_store: UserStore = InMemoryUserStore()


def enable_sql_users(session_factory) -> None:
    """Switch user storage to SQLAlchemy-backed persistence.

    Called from dependencies.py when DATABASE_URL is set.
    Also enables DB-backed rate limiting and token revocation.
    """
    global _user_store, _auth_session_factory
    _user_store = SQLUserStore(session_factory)
    _auth_session_factory = session_factory


def _to_user_read(user_data: dict) -> UserRead:
    return UserRead(**{k: v for k, v in user_data.items() if k != "hashed_password"})


# ---------------------------------------------------------------------------
# Public API (same interface as before)
# ---------------------------------------------------------------------------


def register_user(username: str, email: str, full_name: str, password: str, role: str = "readonly") -> UserRead:
    """Register a new user with password policy enforcement (T21)."""
    if _user_store.get_by_username(username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Benutzername existiert bereits")
    # T21: Validate password strength
    pw_errors = validate_password_strength(password)
    if pw_errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Passwort zu schwach: {'; '.join(pw_errors)}",
        )
    user_id = str(uuid4())
    now = datetime.utcnow()
    user_data = {
        "id": user_id,
        "username": username,
        "email": email,
        "full_name": full_name,
        "hashed_password": hash_password(password),
        "role": role,
        "is_active": True,
        "totp_secret": None,  # T10: TOTP disabled by default
        "totp_enabled": False,
        "created_at": now,
        "updated_at": now,
    }
    _user_store.create(user_data)
    return _to_user_read(user_data)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate a user by username and password with rate limiting (T21)."""
    # T21: Check rate limit
    if check_login_rate_limit(username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Anmeldeversuche. Bitte warten Sie {LOCKOUT_DURATION_MINUTES} Minuten.",
        )
    user = _user_store.get_by_username(username)
    if user is None:
        record_failed_login(username)
        return None
    if not user["is_active"]:
        record_failed_login(username)
        return None
    if not verify_password(password, user["hashed_password"]):
        record_failed_login(username)
        return None
    # Success: clear attempts
    clear_login_attempts(username)
    return user


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get a user by ID."""
    return _user_store.get_by_id(user_id)


def list_users() -> list[UserRead]:
    """List all users."""
    return [_to_user_read(u) for u in _user_store.list_all()]


def update_user(user_id: str, updates: dict) -> UserRead:
    """Update user fields."""
    user = _user_store.update(user_id, updates)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    return _to_user_read(user)


def delete_user(user_id: str) -> None:
    """Delete a user."""
    user = _user_store.delete(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")


def clear_users() -> None:
    """Clear all users (for testing)."""
    _user_store.clear()
    _login_attempts.clear()
    _token_blacklist.clear()
    _blacklist_expiry.clear()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[UserRead]:
    """FastAPI dependency: extract and validate the current user from JWT.

    Returns None if no token is provided (allows unauthenticated access
    to endpoints that don't require auth). Endpoints requiring auth
    should use `require_auth` instead.
    """
    if credentials is None:
        return None
    token_data = decode_token(credentials.credentials)
    if token_data.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger Token-Typ",
        )
    user = get_user_by_id(token_data.sub)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzer nicht gefunden",
        )
    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Benutzerkonto deaktiviert",
        )
    return UserRead(**{k: v for k, v in user.items() if k != "hashed_password"})


async def require_auth(
    user: Optional[UserRead] = Depends(get_current_user),
) -> UserRead:
    """FastAPI dependency: require authenticated user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: str):
    """FastAPI dependency factory: require user to have one of the given roles."""
    async def check_role(user: UserRead = Depends(require_auth)) -> UserRead:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rolle '{user.role}' hat keine Berechtigung für diese Aktion",
            )
        return user
    return check_role
