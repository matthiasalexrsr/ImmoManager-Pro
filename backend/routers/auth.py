"""Authentication router: login, register, refresh, user management."""

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ..auth import (
    authenticate_user,
    check_register_rate_limit,
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
    record_registration_attempt,
    register_user,
    require_auth,
    require_role,
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
    if check_register_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Registrierungsversuche. Bitte versuchen Sie es später erneut.",
        )
    record_registration_attempt(client_ip)
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
    tokens = TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )
    if request is not None and response is not None:
        set_upload_access_cookie(response, request, tokens.access_token)
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
    This prevents replay attacks with stolen refresh tokens.
    """
    token_data = decode_token(payload.refresh_token)
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
    revoke_token(payload.refresh_token)
    tokens = TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )
    if request is not None and response is not None:
        set_upload_access_cookie(response, request, tokens.access_token)
    return tokens


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
    if request is not None and response is not None:
        clear_upload_access_cookie(response, request)
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


@router.get("/users/me/preferences", response_model=None)
def get_my_preferences(user: UserRead = Depends(require_auth)) -> dict:
    """Get current user's preferences."""
    import logging

    session = _get_preferences_session()
    if session is None:
        return _DEFAULT_PREFERENCES.copy()
    try:
        from ..db.orm_models import UserPreferencesORM
        prefs = session.query(UserPreferencesORM).filter(
            UserPreferencesORM.user_id == user.id
        ).first()
        if prefs:
            return _prefs_to_dict(prefs)
    except (ImportError, OSError, RuntimeError):
        logging.getLogger(__name__).warning("Failed to load user preferences, using defaults")
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to load user preferences: %s", exc)
    finally:
        session.close()
    return _DEFAULT_PREFERENCES.copy()


@router.put("/users/me/preferences", response_model=None)
def update_my_preferences(payload: dict, user: UserRead = Depends(require_auth)) -> dict:
    """Update current user's preferences."""
    import logging

    allowed_keys = {"theme", "locale", "sidebar_collapsed", "items_per_page", "date_format", "currency", "default_due_day", "email_notifications", "reminder_days"}
    clean = {k: v for k, v in payload.items() if k in allowed_keys}

    session = _get_preferences_session()
    if session is None:
        return {**_DEFAULT_PREFERENCES, **clean}

    try:
        from ..db.orm_models import UserPreferencesORM
        prefs = session.query(UserPreferencesORM).filter(
            UserPreferencesORM.user_id == user.id
        ).first()
        if prefs:
            for k, v in clean.items():
                setattr(prefs, k, v)
        else:
            prefs = UserPreferencesORM(user_id=user.id, **clean)
            session.add(prefs)
        session.commit()
        return _prefs_to_dict(prefs)
    except (ImportError, OSError, RuntimeError):
        session.rollback()
        logging.getLogger(__name__).warning("Failed to persist user preferences update")
        return {**_DEFAULT_PREFERENCES, **clean}
    except Exception as exc:
        session.rollback()
        logging.getLogger(__name__).warning("Failed to persist user preferences update: %s", exc)
        return {**_DEFAULT_PREFERENCES, **clean}
    finally:
        session.close()


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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
