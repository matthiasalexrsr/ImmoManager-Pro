"""Versioned property workflows and frozen tenancy-change execution state.

Registration/startup/recovery integration is intentionally owned by Root.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class WorkflowTemplateORM(Base):
    __tablename__ = "tenancy_workflow_templates"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("direction IN ('move_in','move_out')", name="ck_workflow_template_direction"),
        Index("ix_workflow_template_scope", "portfolio_id", "property_id", "unit_id", "direction", "created_at", "id"),
        Index(
            "uq_workflow_property_direction",
            "property_id",
            "direction",
            unique=True,
            sqlite_where=text("unit_id IS NULL"),
            postgresql_where=text("unit_id IS NULL"),
        ),
        Index(
            "uq_workflow_unit_direction",
            "unit_id",
            "direction",
            unique=True,
            sqlite_where=text("unit_id IS NOT NULL"),
            postgresql_where=text("unit_id IS NOT NULL"),
        ),
    )


class WorkflowTemplateVersionORM(Base):
    __tablename__ = "tenancy_workflow_template_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("tenancy_workflow_templates.id", ondelete="RESTRICT"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    based_on_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenancy_workflow_template_versions.id", ondelete="RESTRICT")
    )
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_workflow_template_version"),
        CheckConstraint("direction IN ('move_in','move_out')", name="ck_workflow_version_direction"),
        CheckConstraint("state IN ('draft','published','retired')", name="ck_workflow_version_state"),
        CheckConstraint("version > 0", name="ck_workflow_version_positive"),
        Index("ix_workflow_version_scope", "portfolio_id", "property_id", "unit_id", "direction", "version", "id"),
    )


class WorkflowTemplateStepORM(Base):
    __tablename__ = "tenancy_workflow_template_steps"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("tenancy_workflow_template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    stable_key: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_requirement: Mapped[str] = mapped_column(String(16), nullable=False)
    anchor: Mapped[str] = mapped_column(String(32), nullable=False)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False)
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignee_role: Mapped[str | None] = mapped_column(String(32))
    depends_on_step_keys: Mapped[list] = mapped_column(JSON, nullable=False)
    evidence_requirement: Mapped[str] = mapped_column(String(32), nullable=False)
    __table_args__ = (
        UniqueConstraint("version_id", "stable_key", name="uq_workflow_step_key"),
        UniqueConstraint("version_id", "position", name="uq_workflow_step_position"),
        CheckConstraint("position >= 0", name="ck_workflow_step_position"),
        CheckConstraint("default_requirement IN ('required','optional')", name="ck_workflow_step_requirement"),
        CheckConstraint(
            "anchor IN ('previous_contract_end','next_contract_start','move_out_handover','move_in_handover')",
            name="ck_workflow_step_anchor",
        ),
        CheckConstraint(
            "evidence_requirement IN ('none','document_original','handover_protocol','meter_reading')",
            name="ck_workflow_step_evidence",
        ),
        CheckConstraint(
            "(assignee_user_id IS NOT NULL AND assignee_role IS NULL) OR "
            "(assignee_user_id IS NULL AND assignee_role IS NOT NULL)",
            name="ck_workflow_step_one_assignee",
        ),
        Index("ix_workflow_steps_version", "version_id", "position", "id"),
    )


class TenancyChangeORM(Base):
    __tablename__ = "tenancy_changes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"), nullable=False)
    previous_contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    next_contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    move_out_handover_date: Mapped[date | None] = mapped_column(Date)
    move_in_handover_date: Mapped[date | None] = mapped_column(Date)
    move_out_template_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenancy_workflow_template_versions.id", ondelete="RESTRICT")
    )
    move_in_template_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenancy_workflow_template_versions.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("mode IN ('move_out','move_in','turnover')", name="ck_tenancy_change_mode"),
        CheckConstraint("state IN ('draft','active','completed','cancelled')", name="ck_tenancy_change_state"),
        Index("ix_tenancy_change_scope", "portfolio_id", "property_id", "unit_id", "state", "updated_at", "id"),
        Index("ix_tenancy_change_previous", "previous_contract_id", "state", "id"),
        Index("ix_tenancy_change_next", "next_contract_id", "state", "id"),
        Index(
            "uq_active_tenancy_change_previous",
            "previous_contract_id",
            unique=True,
            sqlite_where=text("state='active' AND previous_contract_id IS NOT NULL"),
            postgresql_where=text("state='active' AND previous_contract_id IS NOT NULL"),
        ),
        Index(
            "uq_active_tenancy_change_next",
            "next_contract_id",
            unique=True,
            sqlite_where=text("state='active' AND next_contract_id IS NOT NULL"),
            postgresql_where=text("state='active' AND next_contract_id IS NOT NULL"),
        ),
    )


class WorkflowStepInstanceORM(Base):
    __tablename__ = "tenancy_workflow_step_instances"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenancy_change_id: Mapped[str] = mapped_column(ForeignKey("tenancy_changes.id", ondelete="RESTRICT"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    template_step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    description_snapshot: Mapped[str | None] = mapped_column(Text)
    requirement: Mapped[str] = mapped_column(String(16), nullable=False)
    not_applicable_reason: Mapped[str | None] = mapped_column(Text)
    anchor: Mapped[str] = mapped_column(String(32), nullable=False)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False)
    original_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    depends_on_step_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignee_role: Mapped[str | None] = mapped_column(String(32))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"), unique=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[str | None] = mapped_column(String)
    evidence_requirement: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("tenancy_change_id", "direction", "template_step_key", name="uq_workflow_instance_step"),
        CheckConstraint("direction IN ('move_in','move_out')", name="ck_workflow_instance_direction"),
        CheckConstraint("requirement IN ('required','optional')", name="ck_workflow_instance_requirement"),
        CheckConstraint(
            "state IN ('open','blocked','in_progress','completed','not_applicable')",
            name="ck_workflow_instance_state",
        ),
        CheckConstraint(
            "evidence_requirement IN ('none','document_original','handover_protocol','meter_reading')",
            name="ck_workflow_instance_evidence",
        ),
        CheckConstraint(
            "(assignee_user_id IS NOT NULL AND assignee_role IS NULL) OR "
            "(assignee_user_id IS NULL AND assignee_role IS NOT NULL)",
            name="ck_workflow_instance_one_assignee",
        ),
        Index("ix_workflow_instance_change", "tenancy_change_id", "direction", "due_date", "id"),
    )


class WorkflowEvidenceLinkORM(Base):
    __tablename__ = "tenancy_workflow_evidence_links"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenancy_change_id: Mapped[str] = mapped_column(ForeignKey("tenancy_changes.id", ondelete="RESTRICT"), nullable=False)
    step_id: Mapped[str] = mapped_column(ForeignKey("tenancy_workflow_step_instances.id", ondelete="RESTRICT"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"))
    handover_protocol_id: Mapped[str | None] = mapped_column(ForeignKey("handover_protocols.id", ondelete="RESTRICT"))
    meter_reading_id: Mapped[str | None] = mapped_column(ForeignKey("meter_readings.id", ondelete="RESTRICT"))
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "kind IN ('document_version','handover_protocol','meter_reading')",
            name="ck_workflow_evidence_kind",
        ),
        CheckConstraint(
            "(kind='document_version' AND document_id IS NOT NULL AND document_version_id IS NOT NULL "
            "AND handover_protocol_id IS NULL AND meter_reading_id IS NULL) OR "
            "(kind='handover_protocol' AND document_id IS NULL AND document_version_id IS NULL "
            "AND handover_protocol_id IS NOT NULL AND meter_reading_id IS NULL) OR "
            "(kind='meter_reading' AND document_id IS NULL AND document_version_id IS NULL "
            "AND handover_protocol_id IS NULL AND meter_reading_id IS NOT NULL)",
            name="ck_workflow_evidence_shape",
        ),
        Index("ix_workflow_evidence_step", "step_id", "created_at", "id"),
    )


class WorkflowCommandORM(Base):
    __tablename__ = "tenancy_workflow_commands"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_tenancy_workflow_command"),
        Index("ix_tenancy_workflow_command_subject", "portfolio_id", "subject_type", "subject_id", "created_at", "id"),
    )


TENANCY_WORKFLOW_MODELS = (
    WorkflowTemplateORM,
    WorkflowTemplateVersionORM,
    WorkflowTemplateStepORM,
    TenancyChangeORM,
    WorkflowStepInstanceORM,
    WorkflowEvidenceLinkORM,
    WorkflowCommandORM,
)
