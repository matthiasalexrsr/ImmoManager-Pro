"""Only the authenticated user's private work in progress; no execution queue."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..dependencies import store
from ..form_draft_models import DraftIdentity, DraftWrite
from ..services.form_drafts import DraftError, form_draft
from ..services.portfolio_scope import scope_from_user

router = APIRouter(prefix="/auth/users/me/form-drafts", tags=["Formularentwürfe"])


def response(identity, user, **options):
    try:
        if identity.owner_id != user.id:
            raise DraftError(403, "DRAFT_IDENTITY_CHANGED", "Das Formular gehört nicht zur aktuellen Anmeldung. Bitte erneut öffnen.")
        data = form_draft(store, identity, scope_from_user(user.model_dump(mode="json")), **options)
        return JSONResponse(data, headers={"Cache-Control": "no-store"})
    except DraftError as error:
        return JSONResponse({"error": {"code": error.code, "message": error.detail}}, status_code=error.status_code,
            headers={"Cache-Control": "no-store"})


@router.get("")
def get_draft(owner_id: str = Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"),
        collection: str = Query(min_length=1, max_length=80, pattern=r"^[a-z][a-z/-]*$"),
        entity_id: str | None = Query(None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"),
        form_key: str = Query("crud", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$"), user=Depends(require_auth)):
    return response(DraftIdentity(collection=collection, entity_id=entity_id, form_key=form_key, owner_id=owner_id), user)


@router.put("")
def save_draft(payload: DraftWrite, user=Depends(require_auth)):
    return response(payload, user, write=payload)


@router.delete("")
def discard_draft(owner_id: str = Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"),
        collection: str = Query(min_length=1, max_length=80, pattern=r"^[a-z][a-z/-]*$"),
        entity_id: str | None = Query(None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"),
        form_key: str = Query("crud", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$"),
        expected_revision: str = Query(pattern=r"^[0-9a-f-]{36}$"), user=Depends(require_auth)):
    return response(DraftIdentity(collection=collection, entity_id=entity_id, form_key=form_key, owner_id=owner_id), user, remove_revision=expected_revision)
