"""A coordinator pointer, separate from immutable operational job receipts."""

from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class OperationalSchedulerORM(Base):
    __tablename__ = "operational_scheduler_state"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation_key: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("operational_jobs.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String, nullable=False)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("generation > 0 AND fence >= 0", name="ck_scheduler_versions"),
        CheckConstraint("state IN ('reserved','running','completed','attention','cancelled')", name="ck_scheduler_state"),
    )
