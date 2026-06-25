"""Bridge UI/API field drift without changing existing route contracts."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, create_model
from sqlalchemy import Column, Date, ForeignKey, Numeric, String, Text

from .. import models as model_module
from ..db import orm_models

_APPLIED = False


def _extend_model(name: str, fields: dict[str, tuple[Any, Any]]) -> None:
    model_cls = getattr(model_module, name)
    if not issubclass(model_cls, BaseModel):
        return

    missing = {field_name: spec for field_name, spec in fields.items() if field_name not in model_cls.model_fields}
    if not missing:
        return

    extended = create_model(
        name,
        __base__=model_cls,
        __module__=model_cls.__module__,
        **missing,
    )
    setattr(model_module, name, extended)


def _append_column(model_cls: type[Any], name: str, column: Column[Any]) -> None:
    if name in model_cls.__table__.c:
        return
    setattr(model_cls, name, column)


def ensure_ui_contracts() -> None:
    """Expose fields used by current UI screens in models and SQL metadata."""
    global _APPLIED
    if _APPLIED:
        return

    receivable_fields = {"description": (Optional[str], None)}
    invoice_fields = {
        "invoice_number": (Optional[str], None),
        "payment_reference": (Optional[str], None),
        "category": (Optional[str], None),
        "notes": (Optional[str], None),
    }
    meter_fields = {
        "contract_number": (Optional[str], None),
        "contract_end_date": (Optional[date], None),
    }

    for name in ("ReceivableCreate", "Receivable", "ReceivablePatch"):
        _extend_model(name, receivable_fields)
    for name in ("InvoiceCreate", "Invoice", "InvoicePatch"):
        _extend_model(name, invoice_fields)
    for name in ("MeterCreate", "Meter", "MeterPatch"):
        _extend_model(name, meter_fields)

    _append_column(orm_models.ReceivableORM, "description", Column(Text))
    _append_column(orm_models.ReceivableORM, "statement_id", Column(String))
    _append_column(orm_models.InvoiceORM, "invoice_number", Column(Text))
    _append_column(orm_models.InvoiceORM, "vat_rate", Column(Numeric(12, 2, asdecimal=False), default=19.0))
    _append_column(orm_models.InvoiceORM, "payment_reference", Column(Text))
    _append_column(orm_models.InvoiceORM, "category", Column(Text))
    _append_column(orm_models.InvoiceORM, "notes", Column(Text))
    _append_column(orm_models.InvoiceORM, "source_document_id", Column(String, ForeignKey("documents.id", ondelete="SET NULL")))
    _append_column(orm_models.MeterORM, "contract_number", Column(String(100)))
    _append_column(orm_models.MeterORM, "contract_end_date", Column(Date))

    _APPLIED = True

