"""Frozen listing and correspondence channels in the existing business contexts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import channel_workflows as service
from ..services import marketing_workflows as marketing
from ..services.portal_adapter import ProtocolError

router = APIRouter(tags=["WhatsApp, Post und Immobilienportale"])
public_router = APIRouter(tags=["WhatsApp Webhook"])
Actor = Annotated[UserRead, Depends(require_auth)]


@router.get("/listings/{source_id}/channels/{channel}/preview")
def listing_preview(source_id: str, channel: str, actor: Actor):
    if channel not in ("is24", "openimmo"):
        raise HTTPException(422, "Unbekanntes Portal.")
    return service.source_preview(store, actor.id, channel, source_id)


@router.get("/messages/threads/{source_id}/whatsapp/preview")
def whatsapp_preview(source_id: str, actor: Actor):
    return service.source_preview(store, actor.id, "whatsapp", source_id)


@router.get("/documents/{source_id}/post/preview")
def post_preview(source_id: str, actor: Actor):
    return service.source_preview(store, actor.id, "post", source_id)


@router.get("/messages/channels/{channel}/{source_id}")
def cases(channel: str, source_id: str, actor: Actor, cursor: str | None = None, limit: int = Query(50, ge=1, le=100)):
    return service.list_cases(store, actor.id, channel, source_id, cursor=cursor, limit=limit)


@router.post("/messages/channels/{channel}/{source_id}/prepare")
def prepare(channel: str, source_id: str, payload: service.Prepare, actor: Actor):
    return service.prepare(store, actor.id, channel, source_id, payload)


@router.get("/messages/channel-options")
def channel_options(channel: str, actor: Actor):
    return service.channel_options(store, actor.id, channel)


@router.get("/messages/channel-cases/{identifier}")
def get_case(identifier: str, actor: Actor):
    return service.get(store, actor.id, identifier)


@router.post("/messages/channel-cases/{identifier}/actions")
def action(identifier: str, payload: service.Action, actor: Actor):
    current = service.get(store, actor.id, identifier)
    if payload.action == "receive_media":
        return service.receive_case_media(store, actor.id, identifier, payload)
    if payload.action == "upload_media":
        return service.upload_media(store, actor.id, identifier, payload)
    if current["channel"] == "post":
        return service.post_action(store, actor.id, identifier, payload)
    return service.execute(store, actor.id, identifier, payload)


@router.get("/messages/channel-cases/{identifier}/original")
def original(identifier: str, name: str, actor: Actor):
    with service.work(store, actor.id) as unit:
        case = service.require_case(unit, identifier)
        originals = service.snapshot(case)["originals"]
        stamp = service.progress(case).get("purchased_original")
        if stamp:
            originals = [*originals, stamp]
        media = service.progress(case).get("media_original")
        if media:
            originals = [*originals, media]
        received = service.progress(case).get("received_media")
        if received:
            originals = [*originals, received]
        selected = next((i for i in originals if i["evidence_name"] == name), None)
        if not selected:
            raise HTTPException(404, "Original nicht gefunden.")
        content = service.read_bytes(unit, case, selected)
        return Response(
            content,
            media_type=selected.get("media_type", "application/octet-stream"),
            headers={"Content-Disposition": 'attachment; filename="original.bin"', "X-Content-Type-Options": "nosniff"},
        )


@public_router.get("/channel-webhooks/whatsapp/{connection_id}")
def verify(
    connection_id: str,
    mode: Annotated[str, Query(alias="hub.mode")],
    token: Annotated[str, Query(alias="hub.verify_token")],
    value: Annotated[str, Query(alias="hub.challenge")],
):
    try:
        return Response(service.webhook_challenge(store, connection_id, mode, token, value), media_type="text/plain")
    except ProtocolError as exc:
        raise HTTPException(exc.status_code or 422, str(exc)) from None


@public_router.post("/channel-webhooks/whatsapp/{connection_id}")
async def receive(connection_id: str, request: Request):
    raw = bytearray()
    async for block in request.stream():
        raw.extend(block)
        if len(raw) > 4 * 1024 * 1024:
            raise HTTPException(413, "Webhook zu groß.")
    try:
        return service.receive_webhook(store, connection_id, bytes(raw), request.headers.get("x-hub-signature-256"))
    except ProtocolError as exc:
        raise HTTPException(exc.status_code or 422, str(exc)) from None


@router.get("/listings/{listing_id}/marketing")
def marketing_overview(listing_id: str, actor: Actor):
    return marketing.overview(store, actor.id, listing_id)


@router.post("/listings/{listing_id}/marketing")
def marketing_action(listing_id: str, payload: marketing.MarketingAction, actor: Actor):
    return marketing.action(store, actor.id, listing_id, payload)


@router.get("/listings/{listing_id}/expose")
def local_expose(listing_id: str, source_sha256: str, actor: Actor):
    return Response(
        marketing.expose(store, actor.id, listing_id, source_sha256),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="expose.pdf"', "X-Content-Type-Options": "nosniff"},
    )


@router.get("/messages/channel-cases/{identifier}/events")
def channel_events(identifier: str, actor: Actor, cursor: str | None = None, limit: int = Query(50, ge=1, le=100)):
    return service.event_page(store, actor.id, identifier, cursor=cursor, limit=limit)


@router.get("/integrations/connections/{connection_id}/whatsapp-inbox")
def whatsapp_inbox(connection_id: str, actor: Actor, cursor: str | None = None, limit: int = Query(50, ge=1, le=100)):
    return service.inbox_page(store, actor.id, connection_id, cursor=cursor, limit=limit)


@router.post("/integrations/connections/{connection_id}/whatsapp-inbox/{webhook_id}/assign")
def assign_inbound(connection_id: str, webhook_id: str, payload: service.InboundAssignment, actor: Actor):
    return service.assign_inbound(store, actor.id, connection_id, webhook_id, payload)
