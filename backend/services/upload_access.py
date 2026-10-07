"""Browser-readable uploads use the existing access JWT, never API cookie auth."""

from fastapi import HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials

from ..auth import decode_token, get_current_user

UPLOAD_ACCESS_COOKIE = "immo_upload_access"
UPLOAD_ACCESS_PATH = "/uploads"


def set_upload_access_cookie(response: Response, request: Request, token: str) -> None:
    """Bind the browser cookie to exactly the access token's expiry."""
    token_data = decode_token(token)
    if token_data.type != "access":
        raise ValueError("Upload access requires an access token")
    response.set_cookie(
        UPLOAD_ACCESS_COOKIE,
        token,
        expires=token_data.exp,
        path=UPLOAD_ACCESS_PATH,
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "private, no-store"


def clear_upload_access_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        UPLOAD_ACCESS_COOKIE,
        path=UPLOAD_ACCESS_PATH,
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "private, no-store"


def require_upload_access(request: Request):
    """Only the read-only upload mount calls this; APIs still require Bearer."""
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer":
            token = ""
    else:
        token = request.cookies.get(UPLOAD_ACCESS_COOKIE, "")
    if not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Reuse signature, lifetime, token type, revocation and active-user checks.
    # Callers run this synchronous database work outside the event loop.
    return get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
