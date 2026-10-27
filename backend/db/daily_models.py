"""Personal state; business notifications remain unchanged."""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class InboxEpochORM(Base):
    __tablename__ = 'daily_inbox_epoch'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class DailySessionORM(Base):
    __tablename__ = 'daily_auth_sessions'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class NumberReservationORM(Base):
    __tablename__ = 'daily_number_reservations'
    domain: Mapped[str] = mapped_column(String(80), primary_key=True)
    number: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def install_inbox_epoch(connection):
    """Transactional generation counter; includes Core and non-application writes."""
    connection.exec_driver_sql('INSERT INTO daily_inbox_epoch (id, revision) SELECT 1, 0 WHERE NOT EXISTS (SELECT 1 FROM daily_inbox_epoch WHERE id = 1)')
    if connection.dialect.name == 'sqlite':
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            connection.exec_driver_sql(f'CREATE TRIGGER IF NOT EXISTS daily_notice_{action.lower()} AFTER {action} ON notifications BEGIN UPDATE daily_inbox_epoch SET revision = revision + 1 WHERE id = 1; END')
    elif connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('CREATE OR REPLACE FUNCTION daily_notice_epoch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE daily_inbox_epoch SET revision = revision + 1 WHERE id = 1; RETURN NULL; END $$')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS daily_notice_change ON notifications')
        connection.exec_driver_sql('CREATE TRIGGER daily_notice_change AFTER INSERT OR UPDATE OR DELETE ON notifications FOR EACH STATEMENT EXECUTE FUNCTION daily_notice_epoch()')


@event.listens_for(Base.metadata, 'after_create')
def _inbox_test_schema(metadata, connection, **kwargs):
    # create_all is used by isolated stores. Production uses the additive migration.
    from sqlalchemy import inspect
    if {'notifications', 'daily_inbox_epoch'} <= set(inspect(connection).get_table_names()):
        install_inbox_epoch(connection)


class DailyStateORM(Base):
    __tablename__ = "daily_user_state"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(240), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class DailyCommandORM(Base):
    __tablename__ = "daily_commands"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

class SettingRuleORM(Base):
    __tablename__ = "daily_setting_rules"
    scope: Mapped[str] = mapped_column(String(160), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
