"""Versioned tenancy workflows after contract correspondence.

Revision ID: b2a2b3c4d5e6
Revises: a2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from backend.db.tenancy_workflow_schema import install_guards

revision = "b2a2b3c4d5e6"
down_revision = "a2a2b3c4d5e6"
branch_labels = depends_on = None

TABLES = (
    "tenancy_workflow_templates",
    "tenancy_workflow_template_versions",
    "tenancy_workflow_template_steps",
    "tenancy_changes",
    "tenancy_workflow_step_instances",
    "tenancy_workflow_evidence_links",
    "tenancy_workflow_commands",
)


def _id():
    return sa.Column("id", sa.String(), primary_key=True)


def _fk(name, table, nullable=False):
    return sa.Column(name, sa.String(), sa.ForeignKey(table + ".id", ondelete="RESTRICT"), nullable=nullable)


def upgrade():
    op.create_table(
        TABLES[0], _id(), _fk("portfolio_id", "portfolios"), _fk("property_id", "properties"),
        _fk("unit_id", "units", True), sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("direction IN ('move_in','move_out')", name="ck_workflow_template_direction"),
    )
    op.create_index("ix_workflow_template_scope", TABLES[0],
        ["portfolio_id", "property_id", "unit_id", "direction", "created_at", "id"])
    op.create_index("uq_workflow_property_direction", TABLES[0], ["property_id", "direction"], unique=True,
        sqlite_where=sa.text("unit_id IS NULL"), postgresql_where=sa.text("unit_id IS NULL"))
    op.create_index("uq_workflow_unit_direction", TABLES[0], ["unit_id", "direction"], unique=True,
        sqlite_where=sa.text("unit_id IS NOT NULL"), postgresql_where=sa.text("unit_id IS NOT NULL"))

    op.create_table(
        TABLES[1], _id(), _fk("template_id", TABLES[0]), _fk("portfolio_id", "portfolios"),
        _fk("property_id", "properties"), _fk("unit_id", "units", True),
        sa.Column("direction", sa.String(16), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False), _fk("based_on_version_id", TABLES[1], True),
        sa.Column("revision", sa.String(36), nullable=False), sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("published_at", sa.DateTime()),
        sa.UniqueConstraint("template_id", "version", name="uq_workflow_template_version"),
        sa.CheckConstraint("version > 0", name="ck_workflow_version_positive"),
        sa.CheckConstraint("direction IN ('move_in','move_out')", name="ck_workflow_version_direction"),
        sa.CheckConstraint("state IN ('draft','published','retired')", name="ck_workflow_version_state"),
    )
    op.create_index("ix_workflow_version_scope", TABLES[1],
        ["portfolio_id", "property_id", "unit_id", "direction", "version", "id"])

    op.create_table(
        TABLES[2], _id(), _fk("version_id", TABLES[1]),
        sa.Column("stable_key", sa.String(100), nullable=False), sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False), sa.Column("description", sa.Text()),
        sa.Column("default_requirement", sa.String(16), nullable=False), sa.Column("anchor", sa.String(32), nullable=False),
        sa.Column("offset_days", sa.Integer(), nullable=False), _fk("assignee_user_id", "users", True),
        sa.Column("assignee_role", sa.String(32)), sa.Column("depends_on_step_keys", sa.JSON(), nullable=False),
        sa.Column("evidence_requirement", sa.String(32), nullable=False),
        sa.UniqueConstraint("version_id", "stable_key", name="uq_workflow_step_key"),
        sa.UniqueConstraint("version_id", "position", name="uq_workflow_step_position"),
        sa.CheckConstraint("position >= 0", name="ck_workflow_step_position"),
        sa.CheckConstraint("default_requirement IN ('required','optional')", name="ck_workflow_step_requirement"),
        sa.CheckConstraint("anchor IN ('previous_contract_end','next_contract_start','move_out_handover','move_in_handover')",
                           name="ck_workflow_step_anchor"),
        sa.CheckConstraint("evidence_requirement IN ('none','document_original','handover_protocol','meter_reading')",
                           name="ck_workflow_step_evidence"),
        sa.CheckConstraint("(assignee_user_id IS NOT NULL AND assignee_role IS NULL) OR "
                           "(assignee_user_id IS NULL AND assignee_role IS NOT NULL)",
                           name="ck_workflow_step_one_assignee"),
    )
    op.create_index("ix_workflow_steps_version", TABLES[2], ["version_id", "position", "id"])

    op.create_table(
        TABLES[3], _id(), _fk("portfolio_id", "portfolios"), _fk("property_id", "properties"), _fk("unit_id", "units"),
        _fk("previous_contract_id", "contracts", True), _fk("next_contract_id", "contracts", True),
        sa.Column("mode", sa.String(16), nullable=False), sa.Column("move_out_handover_date", sa.Date()),
        sa.Column("move_in_handover_date", sa.Date()), _fk("move_out_template_version_id", TABLES[1], True),
        _fk("move_in_template_version_id", TABLES[1], True), sa.Column("state", sa.String(16), nullable=False),
        sa.Column("revision", sa.String(36), nullable=False), sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('move_out','move_in','turnover')", name="ck_tenancy_change_mode"),
        sa.CheckConstraint("state IN ('draft','active','completed','cancelled')", name="ck_tenancy_change_state"),
    )
    op.create_index("ix_tenancy_change_scope", TABLES[3],
        ["portfolio_id", "property_id", "unit_id", "state", "updated_at", "id"])
    op.create_index("ix_tenancy_change_previous", TABLES[3], ["previous_contract_id", "state", "id"])
    op.create_index("ix_tenancy_change_next", TABLES[3], ["next_contract_id", "state", "id"])
    op.create_index("uq_active_tenancy_change_previous", TABLES[3], ["previous_contract_id"], unique=True,
        sqlite_where=sa.text("state='active' AND previous_contract_id IS NOT NULL"),
        postgresql_where=sa.text("state='active' AND previous_contract_id IS NOT NULL"))
    op.create_index("uq_active_tenancy_change_next", TABLES[3], ["next_contract_id"], unique=True,
        sqlite_where=sa.text("state='active' AND next_contract_id IS NOT NULL"),
        postgresql_where=sa.text("state='active' AND next_contract_id IS NOT NULL"))

    op.create_table(
        TABLES[4], _id(), _fk("tenancy_change_id", TABLES[3]), _fk("portfolio_id", "portfolios"),
        sa.Column("template_step_key", sa.String(100), nullable=False), sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("title_snapshot", sa.Text(), nullable=False), sa.Column("description_snapshot", sa.Text()),
        sa.Column("requirement", sa.String(16), nullable=False), sa.Column("not_applicable_reason", sa.Text()),
        sa.Column("anchor", sa.String(32), nullable=False), sa.Column("offset_days", sa.Integer(), nullable=False),
        sa.Column("original_due_date", sa.Date(), nullable=False), sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False), sa.Column("depends_on_step_ids", sa.JSON(), nullable=False),
        _fk("assignee_user_id", "users", True), sa.Column("assignee_role", sa.String(32)),
        _fk("task_id", "tasks", True), sa.Column("completed_at", sa.DateTime()), sa.Column("completed_by", sa.String()),
        sa.Column("evidence_requirement", sa.String(32), nullable=False), sa.Column("revision", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenancy_change_id", "direction", "template_step_key", name="uq_workflow_instance_step"),
        sa.UniqueConstraint("task_id", name="uq_workflow_instance_task"),
        sa.CheckConstraint("direction IN ('move_in','move_out')", name="ck_workflow_instance_direction"),
        sa.CheckConstraint("requirement IN ('required','optional')", name="ck_workflow_instance_requirement"),
        sa.CheckConstraint("state IN ('open','blocked','in_progress','completed','not_applicable')",
                           name="ck_workflow_instance_state"),
        sa.CheckConstraint("evidence_requirement IN ('none','document_original','handover_protocol','meter_reading')",
                           name="ck_workflow_instance_evidence"),
        sa.CheckConstraint("(assignee_user_id IS NOT NULL AND assignee_role IS NULL) OR "
                           "(assignee_user_id IS NULL AND assignee_role IS NOT NULL)",
                           name="ck_workflow_instance_one_assignee"),
    )
    op.create_index("ix_workflow_instance_change", TABLES[4],
        ["tenancy_change_id", "direction", "due_date", "id"])

    op.create_table(
        TABLES[5], _id(), _fk("tenancy_change_id", TABLES[3]), _fk("step_id", TABLES[4]),
        _fk("portfolio_id", "portfolios"), sa.Column("kind", sa.String(32), nullable=False),
        _fk("document_id", "documents", True), _fk("document_version_id", "document_versions", True),
        _fk("handover_protocol_id", "handover_protocols", True), _fk("meter_reading_id", "meter_readings", True),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False), sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('document_version','handover_protocol','meter_reading')",
                           name="ck_workflow_evidence_kind"),
        sa.CheckConstraint(
            "(kind='document_version' AND document_id IS NOT NULL AND document_version_id IS NOT NULL "
            "AND handover_protocol_id IS NULL AND meter_reading_id IS NULL) OR "
            "(kind='handover_protocol' AND document_id IS NULL AND document_version_id IS NULL "
            "AND handover_protocol_id IS NOT NULL AND meter_reading_id IS NULL) OR "
            "(kind='meter_reading' AND document_id IS NULL AND document_version_id IS NULL "
            "AND handover_protocol_id IS NULL AND meter_reading_id IS NOT NULL)",
            name="ck_workflow_evidence_shape"),
    )
    op.create_index("ix_workflow_evidence_step", TABLES[5], ["step_id", "created_at", "id"])

    op.create_table(
        TABLES[6], _id(), _fk("portfolio_id", "portfolios"), sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False), sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False), sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_tenancy_workflow_command"),
    )
    op.create_index("ix_tenancy_workflow_command_subject", TABLES[6],
        ["portfolio_id", "subject_type", "subject_id", "created_at", "id"])
    install_guards(op.get_bind())




def downgrade():
    connection = op.get_bind()
    present = set(inspect(connection).get_table_names())
    for table in TABLES:
        if table in present and connection.scalar(text(f'SELECT 1 FROM "{table}" LIMIT 1')) is not None:
            raise RuntimeError("Downgrade would erase retained tenancy workflow history")
    if connection.dialect.name == "sqlite":
        for name in (
            "immo_handover_finalized_update",
            "immo_handover_finalized_delete",
            "immo_finalized_handover_meter_insert",
            "immo_finalized_handover_meter_update",
            "immo_finalized_handover_meter_delete",
        ):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_handover_finalized_guard ON handover_protocols"
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_finalized_handover_meter_guard ON meter_readings"
        )
    for table in reversed(TABLES):
        if table in present:
            op.drop_table(table)
    if connection.dialect.name == "postgresql":
        for name in (
            "immo_tenancy_command_immutable",
            "immo_tenancy_template_step_guard",
            "immo_tenancy_template_version_guard",
            "immo_tenancy_template_root_guard",
            "immo_tenancy_change_guard",
            "immo_tenancy_instance_guard",
            "immo_tenancy_evidence_update_guard",
            "immo_handover_finalized_guard",
            "immo_finalized_handover_meter_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
