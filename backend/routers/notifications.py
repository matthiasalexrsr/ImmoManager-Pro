"""Router for notifications and notification templates.

Includes endpoints for CRUD, mark-as-read, and event-based generation
of notifications (overdue payments, expiring contracts, due tasks).

Route ordering: static paths (/templates, /generate/*) before path params (/{notification_id}).
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import (
    Notification,
    NotificationCreate,
    NotificationPatch,
    NotificationTemplate,
    NotificationTemplateCreate,
    NotificationTemplatePatch,
)
from ..storage import NotFoundError, ValidationError

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
        return store._patch_entity(
            None, template_id, payload, "Benachrichtigungsvorlage nicht gefunden"
        )
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


@router.post("/generate/overdue-payments", response_model=list[Notification], status_code=status.HTTP_201_CREATED)
def generate_overdue_payment_notifications(
    as_of: date | None = Query(None),
) -> list[Notification]:
    """Generate notifications for overdue receivables."""
    check_date = as_of or date.today()
    created: list[Notification] = []

    for receivable in store.list_receivables():
        if receivable.status == "open" and receivable.due_date < check_date:
            tenant_name = "Unbekannt"
            try:
                contract = store.get_contract(receivable.contract_id)
                try:
                    tenant = store.get_tenant(contract.tenant_id)
                    tenant_name = tenant.full_name
                except Exception:
                    pass
            except Exception:
                pass

            notification = store.create_notification(
                NotificationCreate(
                    notification_type="overdue_payment",
                    title=f"Überfällige Zahlung: {tenant_name}",
                    content=f"Forderung über {receivable.amount_due:.2f} EUR fällig am {receivable.due_date} ist überfällig.",
                    severity="warning",
                    entity_type="receivable",
                    entity_id=receivable.id,
                )
            )
            created.append(notification)

    return created


@router.post("/generate/expiring-contracts", response_model=list[Notification], status_code=status.HTTP_201_CREATED)
def generate_expiring_contract_notifications(
    days_ahead: int = Query(90, ge=1, le=365),
    as_of: date | None = Query(None),
) -> list[Notification]:
    """Generate notifications for contracts expiring within the given window."""
    from datetime import timedelta

    check_date = as_of or date.today()
    horizon = check_date + timedelta(days=days_ahead)
    created: list[Notification] = []

    for contract in store.list_contracts():
        if (
            contract.status == "active"
            and contract.end_date is not None
            and check_date <= contract.end_date <= horizon
        ):
            tenant_name = "Unbekannt"
            try:
                tenant = store.get_tenant(contract.tenant_id)
                tenant_name = tenant.full_name
            except Exception:
                pass

            notification = store.create_notification(
                NotificationCreate(
                    notification_type="contract_expiry",
                    title=f"Vertragsende: {contract.contract_number}",
                    content=f"Vertrag {contract.contract_number} (Mieter: {tenant_name}) endet am {contract.end_date}.",
                    severity="info",
                    entity_type="contract",
                    entity_id=contract.id,
                )
            )
            created.append(notification)

    return created


@router.post("/generate/due-tasks", response_model=list[Notification], status_code=status.HTTP_201_CREATED)
def generate_due_task_notifications(
    as_of: date | None = Query(None),
) -> list[Notification]:
    """Generate notifications for overdue or due-today tasks."""
    check_date = as_of or date.today()
    created: list[Notification] = []

    for task in store.list_tasks():
        if (
            task.status == "open"
            and task.due_date is not None
            and task.due_date <= check_date
        ):
            notification = store.create_notification(
                NotificationCreate(
                    notification_type="task_due",
                    title=f"Aufgabe fällig: {task.title}",
                    content=f"Aufgabe '{task.title}' ist fällig seit {task.due_date}.",
                    severity="warning" if task.due_date < check_date else "info",
                    entity_type="task",
                    entity_id=task.id,
                )
            )
            created.append(notification)

    return created


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
) -> list[Notification]:
    results = store.list_notifications()
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
def get_notification(notification_id: str) -> Notification:
    try:
        return store.get_notification(notification_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{notification_id}/read", response_model=Notification)
def mark_notification_read(notification_id: str) -> Notification:
    try:
        return store.mark_notification_read(notification_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{notification_id}", response_model=Notification)
def patch_notification(notification_id: str, payload: NotificationPatch) -> Notification:
    try:
        return store._patch_entity(
            None, notification_id, payload, "Benachrichtigung nicht gefunden"
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: str) -> None:
    try:
        store.delete_notification(notification_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
