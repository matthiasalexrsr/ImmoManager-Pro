"""Read-only authority fence for owned business transactions.

The credential lives only in the request ContextVar. In particular this helper
must not touch an auth session through a second SQLite writer before commit.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException

from .. import auth

_request_credential: ContextVar[str | None] = ContextVar("immo_business_request_credential", default=None)


@contextmanager
def request_authority(token: str | None):
    marker = _request_credential.set(token)
    try:
        yield
    finally:
        _request_credential.reset(marker)


def require_fresh_request_authority(actor_id: str) -> None:
    token = _request_credential.get()
    # Direct domain calls still require their explicit, freshly checked actor.
    # They do not inherit a previous HTTP credential or a system identity.
    if token is None:
        return
    claims = auth.decode_signed_token(token)
    if claims.type != "access" or claims.sub != actor_id or auth.is_token_revoked(token):
        raise HTTPException(401, "Die Anmeldung ist nicht mehr gültig. Neu anmelden und den gespeicherten Vorgang wiederholen.")
