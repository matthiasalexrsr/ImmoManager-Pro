"""Authentication router: login, register, refresh, user management."""

import logging
from ipaddress import ip_address
from typing import cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, StrictBool

from ..auth import (
    authenticate_user,
    clear_login_attempts,
    create_initial_owner,
    decode_token,
    delete_user,
    get_totp_uri,
    get_user_by_id,
    list_users,
    prepare_totp,
    record_failed_login,
    register_user,
    require_auth,
    require_role,
    revoke_token,
    security,
    setup_required,
    update_user,
    verify_totp,
)
from ..models import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserPatch,
    UserRead,
)
from ..services import auth_sessions
from ..services.preferences import DEFAULTS, PreferencesInput, read_preferences, write_preferences

router = APIRouter(prefix="/auth", tags=["Authentication"])


_DEFAULT_PREFERENCES = DEFAULTS


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request) -> UserRead:
    """Private installations accept only accounts approved by an owner."""
    raise HTTPException(status_code=403, detail="Öffentliche Registrierung ist deaktiviert. Bitte wenden Sie sich an den Eigentümer.")


def _is_local_setup_request(request: Request) -> bool:
    def loopback(host: str | None) -> bool:
        if host == "localhost":
            return True
        try:
            return bool(host and ip_address(host).is_loopback)
        except ValueError:
            return False

    # Validate the peer and Host, not forwarded headers. The Host/Origin checks
    # prevent a third-party website from bootstrapping through DNS rebinding.
    if not request.client or not loopback(request.client.host) or not loopback(request.url.hostname):
        return False
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != request.url.netloc or not loopback(parsed.hostname):
            return False
    return True


@router.get("/setup-status")
def get_setup_status(request: Request) -> dict:
    return {
        "setup_required": setup_required(),
        "setup_allowed": _is_local_setup_request(request),
        "registration_open": False,
        "access_model": "private_installation",
    }


@router.post("/setup", response_model=UserRead, status_code=201)
def setup_owner(payload: UserCreate, request: Request) -> UserRead:
    if not _is_local_setup_request(request):
        raise HTTPException(status_code=403, detail="Ersteinrichtung ist nur lokal über localhost oder 127.0.0.1 erlaubt")
    return create_initial_owner(payload.username, payload.email, payload.full_name, payload.password)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request = cast(Request, None)) -> TokenResponse:
    """Authenticate and receive JWT tokens. Enforces TOTP when enabled."""
    user = authenticate_user(payload.username, payload.password, complete=False)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Anmeldedaten",
        )
    # Enforce TOTP when 2FA is enabled for this user
    if user.get("totp_enabled") and user.get("totp_secret"):
        if not payload.totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Zwei-Faktor-Code erforderlich",
                headers={"X-2FA-Required": "true"},
            )
        if not verify_totp(user["totp_secret"], payload.totp_code):
            record_failed_login(payload.username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ungültiger Zwei-Faktor-Code",
            )
    clear_login_attempts(payload.username)
    return auth_sessions.login_pair(user["id"], request.headers.get("user-agent") if request else None)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, request: Request = cast(Request, None)) -> TokenResponse:
    """Rotate once; consumed refresh reuse durably revokes its whole family."""
    return auth_sessions.rotate(payload.refresh_token, request.headers.get("user-agent") if request else None)


@router.post("/logout")
def logout(payload: dict) -> dict:
    """Logout by revoking the provided access and/or refresh tokens."""
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if access_token:
        revoke_token(access_token)
    if refresh_token:
        revoke_token(refresh_token)
    return {"detail": "Erfolgreich abgemeldet"}


class SessionRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: StrictBool


@router.get("/sessions", response_model=None)
def get_sessions(user: UserRead = Depends(require_auth),
                 credentials: HTTPAuthorizationCredentials = Depends(security),
                 offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=1000)):
    claims = decode_token(credentials.credentials)
    return auth_sessions.list_sessions(user.id, claims.sid, offset, limit)


@router.post("/sessions/{session_id}/revoke", response_model=None)
def revoke_session(session_id: str, payload: SessionRevocation, user: UserRead = Depends(require_auth),
                   credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not payload.confirmed:
        raise HTTPException(422, "Bitte den Sitzungswiderruf ausdrücklich bestätigen.")
    claims = decode_token(credentials.credentials)
    return auth_sessions.revoke_own(user.id, session_id, claims.sid)


@router.get("/me", response_model=UserRead)
def get_me(user: UserRead = Depends(require_auth)) -> UserRead:
    """Get current authenticated user's profile."""
    return user


def _get_preferences_session():
    from ..auth import _auth_session_factory
    if _auth_session_factory is None:
        return None
    try:
        # Preferences belong to the same account database that authenticated
        # this user, including isolated installations and runtime store swaps.
        return _auth_session_factory()
    except Exception:
        logging.getLogger(__name__).warning("Could not open display preferences database")
        raise HTTPException(503, "Anzeigeeinstellungen sind derzeit nicht verfügbar.") from None


@router.get("/users/me/preferences", response_model=None)
def get_my_preferences(user: UserRead = Depends(require_auth)) -> dict:
    return read_preferences(user.id, _get_preferences_session())


@router.put("/users/me/preferences", response_model=None)
def update_my_preferences(payload: PreferencesInput, user: UserRead = Depends(require_auth)) -> dict:
    if isinstance(payload, dict):
        payload = PreferencesInput.model_validate(payload)
    return write_preferences(user.id, payload, _get_preferences_session())


@router.get("/users", response_model=list[UserRead])
def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> list[UserRead]:
    """List all users (admin only)."""
    users = list_users()
    return users[skip : skip + limit]


@router.post("/users", response_model=UserRead, status_code=201)
def create_approved_user(payload: UserCreate, user: UserRead = Depends(require_role("eigentuemer"))) -> UserRead:
    """Only installation owners may approve a new account and assign its role."""
    return register_user(payload.username, payload.email, payload.full_name, payload.password, payload.role,
                         portfolio_access=payload.portfolio_access, portfolio_ids=payload.portfolio_ids, actor_id=user.id)


@router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    user_id: str,
    payload: UserPatch,
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> UserRead:
    """Update a user (admin only)."""
    changes = payload.model_dump(exclude_unset=True)

    # Only owners may change user roles.
    if "role" in changes and user.role != "eigentuemer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Eigentümer dürfen Rollen ändern",
        )

    return update_user(user_id, changes, actor_id=user.id)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(
    user_id: str,
    user: UserRead = Depends(require_role("eigentuemer")),
) -> None:
    """Delete a user (owner only)."""
    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Eigenes Konto kann nicht gelöscht werden",
        )
    delete_user(user_id, actor_id=user.id)


# ---------------------------------------------------------------------------
# T10: Two-Factor Authentication (TOTP)
# ---------------------------------------------------------------------------


@router.post("/2fa/setup", response_model=None)
def setup_2fa(user: UserRead = Depends(require_auth)) -> dict:
    """Generate a TOTP secret and return the setup URI for QR code generation."""
    data = prepare_totp(user.id)
    secret = data["totp_secret"]
    uri = get_totp_uri(secret, user.username)
    return {"secret": secret, "uri": uri, "message": "Hinterlegen Sie den Schlüssel in Ihrer Authenticator-App und bestätigen Sie einen Code."}


@router.post("/2fa/verify", response_model=None)
def verify_2fa_setup(
    payload: dict,
    user: UserRead = Depends(require_auth),
) -> dict:
    """Verify a TOTP code and enable 2FA for the user."""
    code = payload.get("code", "")
    user_data = get_user_by_id(user.id)
    if not user_data or not user_data.get("totp_secret"):
        raise HTTPException(status_code=400, detail="2FA nicht eingerichtet. Bitte zuerst /2fa/setup aufrufen.")
    if not verify_totp(user_data["totp_secret"], code):
        raise HTTPException(status_code=400, detail="Ungültiger TOTP-Code")
    update_user(user.id, {"totp_enabled": True})
    return {"enabled": True, "message": "Zwei-Faktor-Authentifizierung aktiviert."}


@router.post("/2fa/disable", response_model=None)
def disable_2fa(
    payload: dict,
    user: UserRead = Depends(require_auth),
) -> dict:
    """Disable 2FA for the current user. Requires current TOTP code."""
    code = payload.get("code", "")
    user_data = get_user_by_id(user.id)
    if not user_data or not user_data.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA ist nicht aktiviert.")
    if not verify_totp(user_data["totp_secret"], code):
        raise HTTPException(status_code=400, detail="Ungültiger TOTP-Code")
    update_user(user.id, {"totp_enabled": False, "totp_secret": None})
    return {"enabled": False, "message": "Zwei-Faktor-Authentifizierung deaktiviert."}


@router.get("/2fa/status", response_model=None)
def get_2fa_status(user: UserRead = Depends(require_auth)) -> dict:
    """Check if 2FA is enabled for the current user."""
    user_data = get_user_by_id(user.id)
    enabled = bool(user_data and user_data.get("totp_enabled"))
    return {"enabled": enabled}
