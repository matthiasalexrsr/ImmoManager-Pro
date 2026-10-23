"""Authenticated communication commands, mounted below the existing office permission area."""
from fastapi import APIRouter, Depends, Query, Response

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services.communication import (
    Assignment,
    Communication,
    Confirmation,
    Decision,
    Draft,
    ReceiveCommand,
    RevisionCommand,
    SkipIncoming,
    Template,
)
from ..services.integrations.manager import integration_manager


def private_response(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Pragma'] = 'no-cache'


router = APIRouter(prefix='/messages/communication', tags=['E-Mail und Posteingang'], dependencies=[Depends(private_response)])


def service():
    return Communication(store, integration_manager)


@router.get('')
def page(response: Response, kind: str = 'outbound', thread_id: str | None = None,
         cursor: str | None = Query(None, max_length=4096), limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)):
    response.headers['Cache-Control'] = 'private, no-store'
    return service().page(user.id, kind=kind, thread_id=thread_id, cursor=cursor, limit=limit)


@router.post('/drafts')
def draft(payload: Draft, user: UserRead = Depends(require_auth)):
    return service().save_draft(payload, user.id)


@router.put('/drafts/{identifier}')
def update(identifier: str, payload: Draft, user: UserRead = Depends(require_auth)):
    return service().save_draft(payload, user.id, identifier)


@router.post('/templates')
def template(payload: Template, user: UserRead = Depends(require_auth)):
    return service().save_template(payload, user.id)


@router.post('/receive/{connection_id}')
def receive(connection_id: str, payload: ReceiveCommand, user: UserRead = Depends(require_auth)):
    return service().receive(connection_id, user.id, command=payload)


@router.get('/connections/choices')
def choices(cursor: str | None = None, user: UserRead = Depends(require_auth)):
    from ..db.integration_connection_models import IntegrationConnectionORM
    from ..services.integrations import connection_storage as dbs
    current = service()
    with current.work(user.id) as unit:
        result = dbs.page(unit, IntegrationConnectionORM, user.id, cursor=cursor,
                          provider_id='email', enabled=True, archived=False)
        result['items'] = [dict(id=row.id, name=row.name, revision=row.revision) for row in result['items']]
        return result


@router.get('/attachments/{document_id}/versions')
def attachment_versions(document_id: str, before: int | None = Query(None, ge=1), user: UserRead = Depends(require_auth)):
    return service().attachment_choices(document_id, user.id, before)


@router.get('/{identifier}')
def detail(identifier: str, response: Response, user: UserRead = Depends(require_auth)):
    response.headers['Cache-Control'] = 'private, no-store'
    return service().get(identifier, user.id)


@router.get('/{identifier}/original')
def original(identifier: str, part: int | None = Query(None, ge=0), user: UserRead = Depends(require_auth)):
    raw, filename, media_type = service().download(identifier, user.id, part)
    from urllib.parse import quote
    return Response(raw, media_type=media_type, headers={'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe='')})


@router.post('/{identifier}/preview')
def preview(identifier: str, payload: RevisionCommand, user: UserRead = Depends(require_auth)):
    return service().preview(identifier, payload, user.id)


@router.post('/{identifier}/confirm')
def confirm(identifier: str, payload: Confirmation, user: UserRead = Depends(require_auth)):
    return service().confirm(identifier, payload, user.id)


@router.post('/{identifier}/retry')
def retry(identifier: str, payload: Confirmation, user: UserRead = Depends(require_auth)):
    return service().confirm(identifier, payload, user.id, retry=True)


@router.post('/{identifier}/reconcile')
def reconcile(identifier: str, payload: Decision, user: UserRead = Depends(require_auth)):
    return service().reconcile(identifier, payload, user.id)


@router.post('/{identifier}/assign')
def assign(identifier: str, payload: Assignment, user: UserRead = Depends(require_auth)):
    return service().assign(identifier, payload, user.id)


@router.post('/mailboxes/{identifier}/skip')
def skip_incoming(identifier: str, payload: SkipIncoming, user: UserRead = Depends(require_auth)):
    return service().skip_incoming(identifier, payload, user.id)


@router.post('/{identifier}/receive-again')
def receive_again(identifier: str, payload: RevisionCommand, user: UserRead = Depends(require_auth)):
    return service().receive_again(identifier, payload, user.id)
