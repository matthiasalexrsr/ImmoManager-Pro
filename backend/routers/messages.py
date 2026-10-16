"""Internal messaging router: threads and messages."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import require_auth
from ..dependencies import store
from ..models import (
    Message,
    MessageCreate,
    MessageThread,
    MessageThreadCreate,
    MessageThreadPatch,
    UserRead,
)
from ..services.ai.message_ai import summarize_thread
from ..services.message_threads import MessageSubmission, message_page, send_message
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/messages", tags=["Nachrichten"])


# --- Threads ---

@router.get("/threads", response_model=list[MessageThread])
def list_threads(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str | None = Query(None),
    sort_order: str = Query("desc"),
) -> list[MessageThread]:
    results = store.list_message_threads()
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("/threads", response_model=MessageThread, status_code=status.HTTP_201_CREATED)
def create_thread(payload: MessageThreadCreate) -> MessageThread:
    try:
        return store.create_message_thread(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/threads/{thread_id}", response_model=MessageThread)
def get_thread(thread_id: str) -> MessageThread:
    try:
        return store.get_message_thread(thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/threads/{thread_id}", response_model=MessageThread)
def patch_thread(thread_id: str, payload: MessageThreadPatch) -> MessageThread:
    try:
        return store._patch_entity("message_thread", thread_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(thread_id: str) -> None:
    try:
        from ..services.communication import ensure_thread_can_delete
        store.get_message_thread(thread_id)
        ensure_thread_can_delete(store, thread_id)
        store.delete_message_thread(thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- Messages within a thread ---

@router.get("/threads/{thread_id}/page")
def get_message_page(
    thread_id: str,
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(100, ge=1, le=250),
    user: UserRead = Depends(require_auth),
) -> dict:
    return message_page(store, thread_id, user.id, cursor=cursor, limit=limit)


@router.get("/threads/{thread_id}/messages", response_model=list[Message])
def list_thread_messages(
    thread_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Message]:
    # Ensure thread exists
    try:
        store.get_message_thread(thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    results = store.list_messages(thread_id=thread_id)
    results.sort(key=lambda m: m.sent_at)
    return results[skip : skip + limit]


@router.post("/threads/{thread_id}/messages", response_model=Message, status_code=status.HTTP_201_CREATED)
def create_message(thread_id: str, payload: MessageSubmission, user: UserRead = Depends(require_auth)) -> Message:
    # Ensure thread exists
    try:
        store.get_message_thread(thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if payload.thread_id != thread_id:
        raise HTTPException(status_code=422, detail="Nachricht und ausgewählte Konversation stimmen nicht überein.")
    try:
        if getattr(payload, "idempotency_key", None) is not None:
            return send_message(store, thread_id, payload, user.id)
        return store.create_message(MessageCreate.model_validate(payload.model_dump()))
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/threads/{thread_id}/summarize")
def summarize_thread_endpoint(thread_id: str) -> dict:
    """AI-powered summarization of a message thread.

    Generates a summary, key points, and action items from all messages
    in the thread. Falls back to extractive summary when AI is unavailable.
    """
    try:
        thread = store.get_message_thread(thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    messages = store.list_messages(thread_id=thread_id)
    messages.sort(key=lambda m: m.sent_at)

    msg_dicts = [{"sender_name": m.sender_name, "body": m.body} for m in messages]
    result = summarize_thread(msg_dicts, subject=thread.subject)

    return {
        "thread_id": thread_id,
        "summary": result.summary,
        "key_points": result.key_points,
        "action_items": result.action_items,
        "sentiment": result.sentiment,
        "ai_model": result.ai_model,
        "message_count": len(messages),
    }
