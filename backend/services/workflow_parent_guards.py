"""Existence-only retention checks inside the ordinary parent writer boundary."""

from typing import Any

from sqlalchemy import inspect, or_, select

from ..db.tenancy_workflow_models import TENANCY_WORKFLOW_MODELS, TenancyChangeORM, WorkflowTemplateORM
from ..storage import ValidationError

MESSAGE = (
    "Mieterwechselvorlagen oder Wechselakten benötigen diese ursprüngliche Zuordnung. "
    "Bezeichnungen und andere Stammdaten können bearbeitet werden; die bisherige "
    "Zuordnung für den Verlauf erhalten und einen neuen Datensatz für das neue Objekt anlegen."
)


def _historical_tenant(row: Any, identifier: str) -> bool:
    snapshot = row.snapshot if isinstance(row.snapshot, dict) else {}
    return any(isinstance(snapshot.get(key), dict) and snapshot[key].get("tenant_id") == identifier
               for key in ("previous_contract", "next_contract"))


def guard_parent_retention(store: Any, kind: str, identifier: str) -> None:
    """No auth reads, new locks, row changes or caller-owned commit/rollback.

    The caller has already authorized the subject and acquired the existing
    shared Memory lock or SQL location locks. Existence queries intentionally
    bypass ORM portfolio filtering: hidden retained facts must prevent deletion
    too, without disclosing their identities or contents.
    """
    kind = "property" if kind == "properties" else kind.removesuffix("s")
    fields = {"portfolio": ("portfolio_id",), "property": ("property_id",),
              "unit": ("unit_id",), "contract": ("previous_contract_id", "next_contract_id")}.get(kind)
    if fields is None and kind != "tenant":
        return
    models = (TenancyChangeORM,) if kind in {"contract", "tenant"} else (WorkflowTemplateORM, TenancyChangeORM)

    def matches(row):
        return _historical_tenant(row, identifier) if kind == "tenant" else any(
            getattr(row, field) == identifier for field in fields or ())

    if not hasattr(store, "db"):
        retained = any(matches(row) for model in models
                       for row in store.__dict__.get(model.__tablename__, {}).values())
    else:
        db = store.db
        names = set(inspect(db.connection()).get_table_names())
        family = {model.__tablename__ for model in TENANCY_WORKFLOW_MODELS}
        if not names & family:
            return  # Entirely absent old family, before explicit runtime migration.
        if not family <= names:
            raise ValidationError("Unvollständige Mieterwechseltabellen. Zuordnung vor Änderungen prüfen.")
        with db.no_autoflush:
            retained = any(isinstance(row, models) and matches(row) for row in db.new | db.dirty | db.deleted)
            for model in models:
                if retained:
                    break
                if kind == "tenant":
                    condition = or_(*(TenancyChangeORM.snapshot[key]["tenant_id"].as_string() == identifier
                                      for key in ("previous_contract", "next_contract")))
                else:
                    condition = or_(*(getattr(model, field) == identifier for field in fields or ()))
                retained = db.connection().execute(select(model.id).where(condition).limit(1)).first() is not None
    if retained:
        raise ValidationError(MESSAGE)


def guard_parent_edit(store: Any, kind: str, current: Any, changes: dict[str, Any]) -> None:
    fields = {"property": ("portfolio_id",), "unit": ("property_id",),
              "contract": ("property_id", "unit_id")}.get(kind, ())
    if any(field in changes and changes[field] != getattr(current, field) for field in fields):
        guard_parent_retention(store, kind, current.id)
