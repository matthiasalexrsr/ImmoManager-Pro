"""Installation-level authentication state, separate from business models."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class AuthSetupORM(Base):
    """A permanent unique marker prevents another first-owner bootstrap."""

    __tablename__ = "auth_setup"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    __table_args__ = (CheckConstraint("id = 1", name="ck_auth_setup_singleton"),)
