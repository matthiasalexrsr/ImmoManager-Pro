"""Authentication router: login, register, refresh, user management."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    delete_user,
    generate_totp_secret,
    get_totp_uri,
    get_user_by_id,
    list_users,
    register_user,
    require_auth,
    require_role,
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

router = APIRouter(prefix="/auth", tags=["Authentication"])


_ALLOWED_SELF_REGISTER_ROLES = {"readonly", "techniker"}


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate) -> UserRead:
    """Register a new user. Self-registration is restricted to readonly/techniker roles."""
    role = payload.role if payload.role in _ALLOWED_SELF_REGISTER_ROLES else "readonly"
    return register_user(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        role=role,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    """Authenticate and receive JWT tokens."""
    user = authenticate_user(payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Anmeldedaten",
        )
    return TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest) -> TokenResponse:
    """Refresh access token using a refresh token."""
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
    return TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )


@router.get("/me", response_model=UserRead)
def get_me(user: UserRead = Depends(require_auth)) -> UserRead:
    """Get current authenticated user's profile."""
    return user


@router.get("/users/me/preferences", response_model=None)
def get_my_preferences(user: UserRead = Depends(require_auth)) -> dict:
    """Get current user's preferences."""
    import logging

    _defaults = {
        "theme": "light",
        "locale": "de-DE",
        "sidebar_collapsed": False,
        "items_per_page": 25,
        "date_format": "DD.MM.YYYY",
        "currency": "EUR",
    }
    try:
        from ..db.session import DATABASE_URL

        if DATABASE_URL and "sqlite" not in DATABASE_URL:
            from ..db.orm_models import UserPreferencesORM
            from ..db.session import SessionLocal
            session = SessionLocal()
            try:
                prefs = session.query(UserPreferencesORM).filter(
                    UserPreferencesORM.user_id == user.id
                ).first()
                if prefs:
                    return {
                        "theme": prefs.theme,
                        "locale": prefs.locale,
                        "sidebar_collapsed": prefs.sidebar_collapsed,
                        "items_per_page": prefs.items_per_page,
                        "date_format": prefs.date_format,
                        "currency": prefs.currency,
                    }
            finally:
                session.close()
    except Exception:
        logging.getLogger(__name__).warning("Failed to load user preferences, using defaults")
    return _defaults


@router.put("/users/me/preferences", response_model=None)
def update_my_preferences(payload: dict, user: UserRead = Depends(require_auth)) -> dict:
    """Update current user's preferences."""
    from ..db.session import DATABASE_URL
    allowed_keys = {"theme", "locale", "sidebar_collapsed", "items_per_page", "date_format", "currency"}
    clean = {k: v for k, v in payload.items() if k in allowed_keys}

    if DATABASE_URL and "sqlite" not in DATABASE_URL:
        from ..db.orm_models import UserPreferencesORM
        from ..db.session import SessionLocal
        session = SessionLocal()
        try:
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
            return {
                "theme": prefs.theme,
                "locale": prefs.locale,
                "sidebar_collapsed": prefs.sidebar_collapsed,
                "items_per_page": prefs.items_per_page,
                "date_format": prefs.date_format,
                "currency": prefs.currency,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    return clean


@router.get("/users", response_model=list[UserRead])
def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> list[UserRead]:
    """List all users (admin only)."""
    users = list_users()
    return users[skip : skip + limit]


@router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    user_id: str,
    payload: UserPatch,
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> UserRead:
    """Update a user (admin only)."""
    return update_user(user_id, payload.model_dump(exclude_unset=True))


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
