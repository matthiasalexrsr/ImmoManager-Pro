"""Authentication router: login, register, refresh, user management."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    delete_user,
    get_user_by_id,
    list_users,
    register_user,
    require_auth,
    require_role,
    update_user,
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
