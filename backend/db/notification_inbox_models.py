"""Explicit personal read-pair metadata; runtime registration belongs to Root."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class NotificationReadStateORM(Base):
    __tablename__ = "notification_read_states"

    actor_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    notification_id: Mapped[str] = mapped_column(
        String, ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    # The staged command supplies actual database UTC time. No caller timestamp.
    read_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "length(actor_id) > 0 AND length(notification_id) > 0",
            name="ck_notification_read_identity",
        ),
    )


NOTIFICATION_READ_MODELS = (NotificationReadStateORM,)
