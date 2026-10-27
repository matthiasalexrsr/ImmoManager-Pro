from typing import Annotated

from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..payment_security_models import AuthorizePayment, RecipientChange, SecurityModeChange
from ..services import payment_security as service
from .invoice_review import _call

router = APIRouter(tags=["Bankdatenfreigabe"])
Actor = Annotated[UserRead, Depends(require_auth)]


@router.get("/invoices/{invoice_id}/payment-authorization")
def read(invoice_id: str, actor: Actor):
    return _call(service.read, store, actor.id, invoice_id)


@router.post("/invoices/{invoice_id}/payment-recipient")
def recipient(invoice_id: str, command: RecipientChange, actor: Actor):
    return _call(service.change_recipient, store, actor.id, invoice_id, command)


@router.post("/invoices/{invoice_id}/payment-authorization")
def authorize(invoice_id: str, command: AuthorizePayment, actor: Actor):
    return _call(service.authorize, store, actor.id, invoice_id, command)


@router.get("/payment-security/settings")
def settings(actor: Actor):
    return _call(service.read_settings, store, actor.id)


@router.put("/payment-security/settings")
def mode(command: SecurityModeChange, actor: Actor):
    return _call(service.set_mode, store, actor.id, command)
