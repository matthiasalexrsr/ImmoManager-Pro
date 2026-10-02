"""Private, expiring work in progress; never a business write queue."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class FormDraftORM(Base):
    __tablename__ = "form_drafts"
    __table_args__ = (Index("idx_form_drafts_user_expiry", "user_id", "expires_at"),)
    # The key binds user, collection, entity/create and explicit form variant.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    collection: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100))
    form_key: Mapped[str] = mapped_column(String(80), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def ensure_form_draft_schema(connection):
    table: Any = FormDraftORM.__table__
    table.create(connection, checkfirst=True)
