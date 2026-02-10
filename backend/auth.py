"""Authentication module: password hashing, JWT tokens, and FastAPI dependencies."""

import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import hashlib
import hmac
import secrets

from jose import JWTError, jwt

from .models import TokenPayload, UserRead

# Configuration via environment variables
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

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


# In-memory user store for non-DB mode; DB mode uses the same interface
_users_by_id: dict[str, dict] = {}
_users_by_username: dict[str, dict] = {}


def register_user(username: str, email: str, full_name: str, password: str, role: str = "readonly") -> UserRead:
    """Register a new user in the in-memory store."""
    if username in _users_by_username:
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
    _users_by_id[user_id] = user_data
    _users_by_username[username] = user_data
    return UserRead(**{k: v for k, v in user_data.items() if k != "hashed_password"})


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate a user by username and password."""
    user = _users_by_username.get(username)
    if user is None:
        return None
    if not user["is_active"]:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get a user by ID."""
    return _users_by_id.get(user_id)


def list_users() -> list[UserRead]:
    """List all users."""
    return [
        UserRead(**{k: v for k, v in u.items() if k != "hashed_password"})
        for u in _users_by_id.values()
    ]


def update_user(user_id: str, updates: dict) -> UserRead:
    """Update user fields."""
    user = _users_by_id.get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    for key, value in updates.items():
        if value is not None and key not in ("id", "hashed_password", "created_at"):
            user[key] = value
    user["updated_at"] = datetime.utcnow()
    return UserRead(**{k: v for k, v in user.items() if k != "hashed_password"})


def delete_user(user_id: str) -> None:
    """Delete a user."""
    user = _users_by_id.pop(user_id, None)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    _users_by_username.pop(user["username"], None)


def clear_users() -> None:
    """Clear all users (for testing)."""
    _users_by_id.clear()
    _users_by_username.clear()


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
