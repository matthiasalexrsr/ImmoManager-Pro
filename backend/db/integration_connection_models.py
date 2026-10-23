"""Private connection configuration, mappings, action receipts and observed source blocks.

Only installation-authorized services use these rows. Secrets are separate
references; non-secret configuration and raw payloads are encrypted as well.
A provider manifest is an allowlist of actions, not proof of live acceptance.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base

CONNECTION_TABLES = (
    "integration_connections", "integration_connection_secrets", "integration_connection_mappings",
    "integration_action_runs", "integration_source_blocks", "integration_connection_events",
)


class IntegrationConnectionORM(Base):
    __tablename__ = "integration_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    config_token: Mapped[str] = mapped_column(Text, nullable=False)
    secret_refs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    legacy_source_hash: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        Index("ix_integration_connections_page", "created_at", "id"),
        Index("uq_integration_default_provider", "provider_id", unique=True,
              sqlite_where=text("is_default = 1"), postgresql_where=text("is_default = true")),
    )


class IntegrationConnectionSecretORM(Base):
    __tablename__ = "integration_connection_secrets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    value_token: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("connection_id", "field_name", "revision", name="uq_integration_connection_secret"),)


class IntegrationConnectionMappingORM(Base):
    __tablename__ = "integration_connection_mappings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    external_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_key_token: Mapped[str] = mapped_column(Text, nullable=False)
    target_kind: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_token: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_token: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(36))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("connection_id", "source_kind", "external_key_hash", name="uq_integration_external_mapping"),
        Index("ix_integration_mapping_page", "connection_id", "created_at", "id"),
    )


class IntegrationActionRunORM(Base):
    __tablename__ = "integration_action_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    command_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    effect: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str | None] = mapped_column(String(60))
    source_id: Mapped[str | None] = mapped_column(String(120))
    source_revision: Mapped[str | None] = mapped_column(String(200))
    config_snapshot_token: Mapped[str] = mapped_column(Text, nullable=False)
    action_manifest_token: Mapped[str] = mapped_column(Text, nullable=False)
    request_token: Mapped[str] = mapped_column(Text, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_token: Mapped[str | None] = mapped_column(Text)
    result_token: Mapped[str | None] = mapped_column(Text)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    result_bytes: Mapped[int | None] = mapped_column(Integer)
    result_blocks: Mapped[int | None] = mapped_column(Integer)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_summary: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("actor_id", "command_key", name="uq_integration_actor_command"),
        Index("ix_integration_run_page", "connection_id", "created_at", "id"),
        Index("ix_integration_run_state", "state", "lease_until", "id"),
    )


class IntegrationSourceBlockORM(Base):
    __tablename__ = "integration_source_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("integration_action_runs.id", ondelete="RESTRICT"), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    data_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("run_id", "category", "sequence", name="uq_integration_source_block"),
        Index("ix_integration_source_hash", "run_id", "category", "sha256"),
    )


class IntegrationConnectionEventORM(Base):
    __tablename__ = "integration_connection_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("integration_action_runs.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    detail_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index("ix_integration_event_page", "connection_id", "created_at", "id"),)
