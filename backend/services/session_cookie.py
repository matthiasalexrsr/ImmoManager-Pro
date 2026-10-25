"""The browser app's refresh token in an HttpOnly cookie instead of script-readable storage.

The app asks for this with the header ``X-Token-Transport: cookie`` on login and refresh. Its refresh token
then never appears in a response body, so script running in the page (an XSS) cannot carry it away; the
cookie is HttpOnly, Secure over HTTPS, SameSite=Strict and sent only to the auth endpoints. A refresh by
cookie needs the same header: a custom header cannot be sent cross-site without a CORS preflight, which the
configured origins refuse, so another site cannot make the browser renew the session (CSRF). API clients
keep sending and receiving the refresh token in the body.
"""

from fastapi import Request, Response

from ..auth import decode_token

REFRESH_COOKIE = "immo_refresh"
REFRESH_PATH = "/api/v1/auth"
TRANSPORT_HEADER = "x-token-transport"


def wants_cookie(request: Request | None) -> bool:
    return request is not None and request.headers.get(TRANSPORT_HEADER, "").strip().lower() == "cookie"


def cookie_token(request: Request | None) -> str:
    return (request.cookies.get(REFRESH_COOKIE, "") if request is not None else "").strip()


def set_refresh_cookie(response: Response, request: Request, token: str) -> None:
    token_data = decode_token(token)
    if token_data.type != "refresh":
        raise ValueError("The session cookie holds a refresh token")
    response.set_cookie(REFRESH_COOKIE, token, expires=token_data.exp, path=REFRESH_PATH,
                        secure=request.url.scheme == "https", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "private, no-store"


def clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, secure=request.url.scheme == "https",
                           httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "private, no-store"
