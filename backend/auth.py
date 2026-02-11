"""Authentication module: password hashing, JWT tokens, and FastAPI dependencies.

Supports two user storage backends:
  - InMemoryUserStore (default, for tests)
  - SQLUserStore (when enable_sql_users() is called with a session)
"""

import hashlib
import hmac
import logging
import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .models import TokenPayload, UserRead

logger = logging.getLogger(__name__)

# Configuration via environment variables
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

if SECRET_KEY == "dev-secret-key-change-in-production":
    logger.warning("JWT_SECRET_KEY is using the default value. Set JWT_SECRET_KEY env var in production!")

# HTTP Bearer scheme
security = HTTPBearer(auto_error=False)

# Number of PBKDF2 iterations (OWASP recommended minimum for SHA-256)
_PBKDF2_ITERATIONS = 600_000


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
    """Create a JWT access token."""
    expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expires, "type": "access"}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token."""
    expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "exp": expires, "type": "refresh"}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT token."""
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

    def _to_dict(self, orm_obj) -> dict:
        return {
            "id": orm_obj.id,
            "username": orm_obj.username,
            "email": orm_obj.email,
            "full_name": orm_obj.full_name,
            "hashed_password": orm_obj.hashed_password,
            "role": orm_obj.role,
            "is_active": orm_obj.is_active,
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
            session.close()

    def get_by_username(self, username: str) -> Optional[dict]:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            obj = session.query(UserORM).filter(UserORM.username == username).first()
            return self._to_dict(obj) if obj else None
        finally:
            session.close()

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
            session.close()

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
            session.close()

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
            session.close()

    def list_all(self) -> list[dict]:
        from .db.orm_models import UserORM
        session = self._session_factory()
        try:
            return [self._to_dict(obj) for obj in session.query(UserORM).all()]
        finally:
            session.close()

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
            session.close()


# Default: in-memory store
_user_store: UserStore = InMemoryUserStore()


def enable_sql_users(session_factory) -> None:
    """Switch user storage to SQLAlchemy-backed persistence.

    Called from dependencies.py when DATABASE_URL is set.
    """
    global _user_store
    _user_store = SQLUserStore(session_factory)


def _to_user_read(user_data: dict) -> UserRead:
    return UserRead(**{k: v for k, v in user_data.items() if k != "hashed_password"})


# ---------------------------------------------------------------------------
# Public API (same interface as before)
# ---------------------------------------------------------------------------


def register_user(username: str, email: str, full_name: str, password: str, role: str = "readonly") -> UserRead:
    """Register a new user."""
    if _user_store.get_by_username(username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Benutzername existiert bereits")
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
        "created_at": now,
        "updated_at": now,
    }
    _user_store.create(user_data)
    return _to_user_read(user_data)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate a user by username and password."""
    user = _user_store.get_by_username(username)
    if user is None:
        return None
    if not user["is_active"]:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
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
