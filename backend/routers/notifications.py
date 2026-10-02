"""Router for notifications and notification templates.

Includes endpoints for CRUD, mark-as-read, and event-based generation
of notifications (overdue payments, expiring contracts, due tasks).

Route ordering: static paths (/templates, /generate/*) before path params (/{notification_id}).
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import require_auth
from ..dependencies import store
from ..models import (
    Notification,
    NotificationCreate,
    NotificationPatch,
    NotificationTemplate,
    NotificationTemplateCreate,
    NotificationTemplatePatch,
    UserRead,
)
from ..services.operational_schedule import generate_notifications, notification_visible
from ..services.recurrence import CatchUpLimit
from ..storage import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Benachrichtigungen"])


# ---------------------------------------------------------------------------
# Notification Templates (static path before /{notification_id})
# ---------------------------------------------------------------------------


@router.get("/templates", response_model=list[NotificationTemplate])
def list_notification_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    notification_type: str | None = Query(None),
) -> list[NotificationTemplate]:
    results = store.list_notification_templates()
    if notification_type:
        results = [r for r in results if r.notification_type == notification_type]
    return results[skip : skip + limit]


@router.post("/templates", response_model=NotificationTemplate, status_code=status.HTTP_201_CREATED)
def create_notification_template(payload: NotificationTemplateCreate) -> NotificationTemplate:
    try:
        return store.create_notification_template(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/templates/{template_id}", response_model=NotificationTemplate)
def get_notification_template(template_id: str) -> NotificationTemplate:
    try:
        return store.get_notification_template(template_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/templates/{template_id}", response_model=NotificationTemplate)
def update_notification_template(template_id: str, payload: NotificationTemplateCreate) -> NotificationTemplate:
    try:
        return store.update_notification_template(template_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/templates/{template_id}", response_model=NotificationTemplate)
def patch_notification_template(template_id: str, payload: NotificationTemplatePatch) -> NotificationTemplate:
    try:
        return store._patch_entity("notification_template", template_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification_template(template_id: str) -> None:
    try:
        store.delete_notification_template(template_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Event-based notification generation (static paths before /{notification_id})
# ---------------------------------------------------------------------------


def _generated(kind, as_of, days_ahead=90):
    try:
        return generate_notifications(store, kind, as_of if isinstance(as_of, date) else date.today(), days_ahead=days_ahead)
    except (ValidationError, CatchUpLimit) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/generate/overdue-payments", response_model=list[Notification], status_code=201)
def generate_overdue_payment_notifications(as_of: date | None = Query(None)) -> list[Notification]:
    return _generated("overdue", as_of)


@router.post("/generate/expiring-contracts", response_model=list[Notification], status_code=201)
def generate_expiring_contract_notifications(days_ahead: int = Query(90, ge=1, le=365), as_of: date | None = Query(None)) -> list[Notification]:
    return _generated("contracts", as_of, days_ahead if isinstance(days_ahead, int) else 90)


@router.post("/generate/due-tasks", response_model=list[Notification], status_code=201)
def generate_due_task_notifications(as_of: date | None = Query(None)) -> list[Notification]:
    return _generated("due_tasks", as_of)


# ---------------------------------------------------------------------------
# Notifications (path params after static paths)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[Notification])
def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: str | None = Query(None, alias="status"),
    notification_type: str | None = Query(None),
    severity: str | None = Query(None),
    user: UserRead = Depends(require_auth),
) -> list[Notification]:
    results = store.list_notifications()
    if isinstance(user, UserRead):
        results = [item for item in results if notification_visible(store, item.id, user.role)]
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    if notification_type:
        results = [r for r in results if r.notification_type == notification_type]
    if severity:
        results = [r for r in results if r.severity == severity]
    return results[skip : skip + limit]


@router.post("", response_model=Notification, status_code=status.HTTP_201_CREATED)
def create_notification(payload: NotificationCreate) -> Notification:
    try:
        return store.create_notification(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{notification_id}", response_model=Notification)
def get_notification(notification_id: str, user: UserRead = Depends(require_auth)) -> Notification:
    try:
        if isinstance(user, UserRead) and not notification_visible(store, notification_id, user.role):
            raise HTTPException(404, "Benachrichtigung nicht gefunden")
        return store.get_notification(notification_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{notification_id}", response_model=Notification)
def update_notification(notification_id: str, payload: NotificationCreate, user: UserRead = Depends(require_auth)) -> Notification:
    try:
        if isinstance(user, UserRead) and not notification_visible(store, notification_id, user.role):
            raise HTTPException(404, "Benachrichtigung nicht gefunden")
        return store.update_notification(notification_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{notification_id}/read", response_model=Notification)
def mark_notification_read(notification_id: str, user: UserRead = Depends(require_auth)) -> Notification:
    try:
        if isinstance(user, UserRead) and not notification_visible(store, notification_id, user.role):
            raise HTTPException(404, "Benachrichtigung nicht gefunden")
        return store.mark_notification_read(notification_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{notification_id}", response_model=Notification)
def patch_notification(notification_id: str, payload: NotificationPatch, user: UserRead = Depends(require_auth)) -> Notification:
    try:
        if isinstance(user, UserRead) and not notification_visible(store, notification_id, user.role):
            raise HTTPException(404, "Benachrichtigung nicht gefunden")
        return store._patch_entity("notification", notification_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: str, user: UserRead = Depends(require_auth)) -> None:
    try:
        if isinstance(user, UserRead) and not notification_visible(store, notification_id, user.role):
            raise HTTPException(404, "Benachrichtigung nicht gefunden")
        store.delete_notification(notification_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
