"""Authentication router: login, register, refresh, user management."""

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ..auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    delete_user,
    generate_totp_secret,
    get_totp_uri,
    get_user_by_id,
    has_users,
    list_users,
    normalize_access,
    register_user,
    require_auth,
    require_role,
    reserve_registration_attempt,
    revoke_token,
    set_user_password,
    update_user,
    verify_totp,
)
from ..config import settings
from ..dependencies import store
from ..models import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserPasswordReset,
    UserPatch,
    UserRead,
)
from ..services.session_cookie import clear_refresh_cookie, cookie_token, set_refresh_cookie, wants_cookie
from ..services.upload_access import clear_upload_access_cookie, set_upload_access_cookie

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Serialises the "first account becomes owner" check against concurrent sign-ups.
_registration_lock = threading.Lock()


@router.get("/registration-status")
def registration_status() -> dict:
    """Public: tells the login page whether sign-up is possible."""
    initial_setup = not has_users()
    return {
        "initial_setup": initial_setup,
        "open": initial_setup or settings.allow_self_registration,
    }


_DEFAULT_PREFERENCES = {
    "theme": "light",
    "locale": "de-DE",
    "sidebar_collapsed": False,
    "items_per_page": 25,
    "date_format": "DD.MM.YYYY",
    "currency": "EUR",
    "default_due_day": 1,
    "email_notifications": "important",
    "reminder_days": "7",
}


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request) -> UserRead:
    """Register a new account.

    The first account ever created becomes the owner (initial setup).
    Afterwards sign-up is closed unless ALLOW_SELF_REGISTRATION is enabled,
    and self-registered accounts are always read-only.
    """
    client_ip = request.client.host if request.client else "unknown"
    if reserve_registration_attempt(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Registrierungsversuche. Bitte versuchen Sie es später erneut.",
        )
    with _registration_lock:
        if not has_users():
            role = "eigentuemer"
        elif settings.allow_self_registration:
            role = "readonly"
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Selbstregistrierung ist deaktiviert. Bitte wenden Sie sich an den Eigentümer.",
            )
        return register_user(
            username=payload.username,
            email=payload.email,
            full_name=payload.full_name,
            password=payload.password,
            role=role,
        )


# FastAPI needs concrete Request/Response annotations for framework injection.
# None defaults preserve direct Python callers; the guards below handle them.
@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> TokenResponse:
    """Authenticate and receive JWT tokens. Enforces TOTP when enabled."""
    user = authenticate_user(payload.username, payload.password)
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ungültiger Zwei-Faktor-Code",
            )
    from uuid import uuid4
    session_id = str(uuid4())
    tokens = TokenResponse(
        access_token=create_access_token(user["id"], session_id),
        refresh_token=create_refresh_token(user["id"], session_id),
    )
    return _deliver(tokens, request, response)


def _deliver(tokens: TokenResponse, request: Request | None, response: Response | None) -> TokenResponse:
    """The browser app gets its refresh token only as an HttpOnly cookie (services/session_cookie)."""
    if request is None or response is None:
        return tokens
    set_upload_access_cookie(response, request, tokens.access_token)
    if wants_cookie(request) and tokens.refresh_token:
        set_refresh_cookie(response, request, tokens.refresh_token)
        return TokenResponse(access_token=tokens.access_token)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshRequest,
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> TokenResponse:
    """Refresh access token using a refresh token.

    Implements token rotation: the old refresh token is revoked on use,
    and a new refresh token is issued alongside the new access token.
    This prevents replay attacks with stolen refresh tokens. The browser app sends no
    token: it is identified by its HttpOnly cookie, and only together with its header.
    """
    token = payload.refresh_token or (cookie_token(request) if wants_cookie(request) else "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Keine Sitzung zum Erneuern. Bitte erneut anmelden.",
        )
    token_data = decode_token(token)
    if token_data.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger Refresh-Token",
        )
    user = get_user_by_id(token_data.sub)
    if user is None or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzer nicht gefunden oder deaktiviert",
        )
    # Rotate: revoke the old refresh token so it cannot be reused
    revoke_token(token, require_unrevoked=True)
    tokens = TokenResponse(
        access_token=create_access_token(user["id"], token_data.sid),
        refresh_token=create_refresh_token(user["id"], token_data.sid),
    )
    return _deliver(tokens, request, response)


@router.post("/logout")
def logout(
    payload: dict,
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> dict:
    """Logout by revoking the provided access and/or refresh tokens."""
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if access_token:
        revoke_token(access_token)
    if refresh_token:
        revoke_token(refresh_token)
    if cookie_token(request):
        revoke_token(cookie_token(request))
    if request is not None and response is not None:
        clear_upload_access_cookie(response, request)
        if cookie_token(request) or wants_cookie(request):
            clear_refresh_cookie(response, request)
    return {"detail": "Erfolgreich abgemeldet"}


@router.get("/me", response_model=UserRead)
def get_me(
    user: UserRead = Depends(require_auth),
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> UserRead:
    """Get current authenticated user's profile."""
    if request is not None and response is not None:
        token = request.headers["authorization"].partition(" ")[2]
        set_upload_access_cookie(response, request, token)
    return user


@router.get("/me/permissions")
def get_my_permissions(user: UserRead = Depends(require_auth)) -> dict:
    """What the signed-in user may change: `write` is null for everything, else path prefixes."""
    from ..permissions import write_areas

    return {"role": user.role, "write": write_areas(user.role)}


def _get_preferences_session():
    """Return a DB session for preferences, or None if SQL is unavailable."""
    try:
        from ..dependencies import _use_sql_store
        if not _use_sql_store:
            return None
        from ..db.session import SessionLocal
        return SessionLocal()
    except Exception:
        logging.getLogger(__name__).debug("Could not create preferences DB session", exc_info=True)
        return None


def _prefs_to_dict(prefs) -> dict:
    return {
        "theme": prefs.theme,
        "locale": prefs.locale,
        "sidebar_collapsed": prefs.sidebar_collapsed,
        "items_per_page": prefs.items_per_page,
        "date_format": prefs.date_format,
        "currency": prefs.currency,
        "default_due_day": prefs.default_due_day,
        "email_notifications": prefs.email_notifications,
        "reminder_days": prefs.reminder_days,
    }


def private_settings(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


@router.get("/users/me/preferences", response_model=None, dependencies=[Depends(private_settings)])
def get_my_preferences(user: UserRead = Depends(require_auth)) -> dict:
    from ..services.settings_catalogue import prefs
    return prefs(store, user.id)


@router.put("/users/me/preferences", response_model=None, dependencies=[Depends(private_settings)])
def update_my_preferences(payload: dict, user: UserRead = Depends(require_auth)) -> dict:
    from uuid import uuid4

    from ..services.settings_catalogue import DEFAULTS, prefs, update
    clean = {key: value for key, value in payload.items() if key in DEFAULTS}
    expected = payload.get("_revision", prefs(store, user.id)["_revision"])
    result = update(store, user.id, clean, base_revision=expected, idempotency_key=str(uuid4()))
    return result["response"]


@router.get("/users/me/settings", dependencies=[Depends(private_settings)])
def my_settings(property_id: str | None = None, user: UserRead = Depends(require_auth)):
    from ..services.settings_catalogue import catalogue
    return catalogue(store, user.id, property_id)


@router.get("/users/me/settings/effective", dependencies=[Depends(private_settings)])
def effective_settings(property_id: str | None = None, user: UserRead = Depends(require_auth)):
    from ..services.settings_catalogue import effective_values
    return effective_values(store, user.id, property_id)


@router.put("/users/me/settings", dependencies=[Depends(private_settings)])
def write_settings(payload: dict, user: UserRead = Depends(require_auth)):
    from ..services.settings_catalogue import update
    if set(payload) - {"values", "base_revision", "idempotency_key", "scope", "reset"}:
        raise HTTPException(422, "Unbekannte Einstellungsfelder.")
    if type(payload.get("base_revision")) is not int or payload["base_revision"] < 0:
        raise HTTPException(422, "Erwartete Revision fehlt.")
    key = payload.get("idempotency_key")
    if not isinstance(key, str) or not 8 <= len(key) <= 120 or not isinstance(payload.get("values"), dict):
        raise HTTPException(422, "Ungültiger Änderungsbefehl.")
    if not isinstance(payload.get("scope", "personal"), str) or type(payload.get("reset", False)) is not bool:
        raise HTTPException(422, "Ungültiger Geltungsbereich.")
    return update(store, user.id, **payload)


class DraftDefaultsCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: str = Field(max_length=80)
    property_id: str | None = Field(None, max_length=120)
    expected_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    idempotency_key: str = Field(min_length=8, max_length=120)


class SessionRevokeCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(min_length=8, max_length=120)


@router.get('/users/me/settings/draft-defaults', dependencies=[Depends(private_settings)])
def draft_defaults(context: str, property_id: str | None = None, user: UserRead = Depends(require_auth)):
    from ..services.setting_consumers import preview
    return preview(store, user.id, context, property_id)


@router.post('/users/me/settings/draft-defaults', dependencies=[Depends(private_settings)])
def apply_draft_defaults(payload: DraftDefaultsCommand, user: UserRead = Depends(require_auth)):
    from ..services.setting_consumers import apply
    return apply(store, user.id, payload.model_dump())


@router.get('/users/me/settings/sessions', dependencies=[Depends(private_settings)])
def settings_sessions(request: Request, user: UserRead = Depends(require_auth)):
    from ..services.daily_sessions import inventory
    token = request.headers.get('authorization', '').partition(' ')[2]
    return inventory(store, user.id, decode_token(token).sid)


@router.post('/users/me/settings/sessions/{identifier}/revoke', dependencies=[Depends(private_settings)])
def revoke_settings_session(identifier: str, payload: SessionRevokeCommand, user: UserRead = Depends(require_auth)):
    from ..services.daily_sessions import revoke
    return revoke(store, user.id, identifier, payload.model_dump())


@router.get('/users/me/settings/bank-import-profile', dependencies=[Depends(private_settings)])
def bank_profile(user: UserRead = Depends(require_auth)):
    from ..services.setting_consumers import bank_import_profile
    return bank_import_profile(store, user.id)


@router.get('/users/me/settings/selected-connection', dependencies=[Depends(private_settings)])
def selected_connection_profile(user: UserRead = Depends(require_auth)):
    from ..services.setting_consumers import selected_connection
    return {'selection': selected_connection(store, user.id)}


@router.get('/users/me/settings/configuration-contract', dependencies=[Depends(private_settings)])
def configuration_contract(user: UserRead = Depends(require_auth)):
    from ..services.setting_consumers import configuration_contract
    return configuration_contract(store, user.id)


@router.get('/users/me/settings/notification-email-selection', dependencies=[Depends(private_settings)])
def notification_email_selection(cursor: str | None = Query(None, max_length=4096), limit: int = Query(100, ge=1, le=200), user: UserRead = Depends(require_auth)):
    from ..services.settings_catalogue import email_selection
    return email_selection(store, user.id, cursor=cursor, limit=limit)


@router.get("/users", response_model=list[UserRead])
def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> list[UserRead]:
    """List all users (admin only)."""
    users = list_users()
    return users[skip : skip + limit]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> UserRead:
    """Create an account (admin only). Only owners may assign roles other than read-only."""
    if payload.role != "readonly" and user.role != "eigentuemer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Eigentümer dürfen Rollen vergeben",
        )
    granted = "portfolio_access" in payload.model_fields_set or "portfolio_ids" in payload.model_fields_set
    if granted and user.role != "eigentuemer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Nur Eigentümer dürfen Portfolios zuweisen")
    _require_portfolios(payload.portfolio_access, payload.portfolio_ids)
    return register_user(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role,
        portfolio_access=payload.portfolio_access,
        portfolio_ids=payload.portfolio_ids,
    )


def _require_portfolios(mode: str | None, ids: list[str] | None) -> None:
    """A selected assignment names portfolios that exist."""
    if mode != "selected":
        return
    known = {portfolio.id for portfolio in store.list_portfolios()}
    unknown = sorted(set(ids or ()) - known)
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Unbekannte Portfolios: " + ", ".join(unknown))


def _load_target(user_id: str) -> dict:
    target = get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    return target


def _require_may_manage(actor: UserRead, target: dict) -> None:
    """Managers may only administer read-only accounts; owners may administer everyone."""
    if actor.role != "eigentuemer" and target["role"] != "readonly":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Eigentümer dürfen Konten mit Schreibrechten verwalten",
        )


def _is_last_active_owner(target: dict) -> bool:
    if target["role"] != "eigentuemer" or not target["is_active"]:
        return False
    owners = [u for u in list_users() if u.role == "eigentuemer" and u.is_active]
    return len(owners) <= 1


@router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    user_id: str,
    payload: UserPatch,
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> UserRead:
    """Update a user (admin only)."""
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    # Only owners may change user roles.
    if "role" in changes and user.role != "eigentuemer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Eigentümer dürfen Rollen ändern",
        )
    target = _load_target(user_id)
    _require_may_manage(user, target)
    if {"portfolio_access", "portfolio_ids"} & changes.keys():
        if user.role != "eigentuemer":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Nur Eigentümer dürfen Portfolios zuweisen")
        if "portfolio_access" not in changes:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                                detail="Portfolios werden zusammen mit der Zugriffsart geändert")
        _require_portfolios(changes["portfolio_access"], changes.get("portfolio_ids"))
        changes.update(normalize_access(changes.get("role", target["role"]), changes["portfolio_access"],
                                        changes.get("portfolio_ids")),
                       portfolio_access_origin="owner_assignment")
    elif changes.get("role") == "eigentuemer":
        changes.update(normalize_access("eigentuemer", "all", None), portfolio_access_origin="owner")

    demotes = changes.get("role", target["role"]) != target["role"]
    deactivates = changes.get("is_active") is False and target["is_active"]
    if user_id == user.id and (demotes or deactivates):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Eigene Rolle und eigener Kontostatus können nicht geändert werden",
        )
    if (demotes or deactivates) and _is_last_active_owner(target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mindestens ein aktiver Eigentümer muss erhalten bleiben",
        )

    return update_user(user_id, changes)


@router.post("/users/{user_id}/password", response_model=UserRead)
def reset_user_password(
    user_id: str,
    payload: UserPasswordReset,
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> UserRead:
    """Set a new password for an account (admin only)."""
    _require_may_manage(user, _load_target(user_id))
    return set_user_password(user_id, payload.password)


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
    if _is_last_active_owner(_load_target(user_id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mindestens ein aktiver Eigentümer muss erhalten bleiben",
        )
    delete_user(user_id)


# ---------------------------------------------------------------------------
# T10: Two-Factor Authentication (TOTP)
# ---------------------------------------------------------------------------


@router.post("/2fa/setup", response_model=None)
def setup_2fa(user: UserRead = Depends(require_auth)) -> dict:
    """Generate a TOTP secret and return the setup URI for QR code generation."""
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user.username)
    # Store secret temporarily (not yet enabled)
    update_user(user.id, {"totp_secret": secret})
    return {"secret": secret, "uri": uri, "message": "Scannen Sie den QR-Code mit einer Authenticator-App."}


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
