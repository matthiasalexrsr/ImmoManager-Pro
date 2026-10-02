"""Versioned tenancy workflows after contract correspondence.

Revision ID: b2a2b3c4d5e6
Revises: a2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

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


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS immo_tenancy_commands_{action.lower()} "
                f"BEFORE {action} ON tenancy_workflow_commands BEGIN "
                "SELECT RAISE(ABORT,'tenancy workflow command receipt is immutable'); END"
            )
            connection.exec_driver_sql(
                f"""CREATE TRIGGER IF NOT EXISTS immo_tenancy_template_steps_{action.lower()}
                BEFORE {action} ON tenancy_workflow_template_steps
                WHEN (SELECT state FROM tenancy_workflow_template_versions WHERE id=OLD.version_id)<>'draft'
                BEGIN SELECT RAISE(ABORT,'published tenancy workflow steps are immutable'); END"""
            )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_template_version_frozen
            BEFORE UPDATE ON tenancy_workflow_template_versions
            WHEN OLD.state IN ('published','retired') AND (
              NEW.template_id IS NOT OLD.template_id OR NEW.portfolio_id IS NOT OLD.portfolio_id OR
              NEW.property_id IS NOT OLD.property_id OR NEW.unit_id IS NOT OLD.unit_id OR
              NEW.direction IS NOT OLD.direction OR NEW.version IS NOT OLD.version OR
              NEW.based_on_version_id IS NOT OLD.based_on_version_id OR NEW.created_by IS NOT OLD.created_by OR
              NEW.created_at IS NOT OLD.created_at OR NEW.published_at IS NOT OLD.published_at OR
              OLD.state='retired' OR NEW.state<>'retired')
            BEGIN SELECT RAISE(ABORT,'published tenancy workflow version is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_template_version_delete
            BEFORE DELETE ON tenancy_workflow_template_versions
            BEGIN SELECT RAISE(ABORT,'tenancy workflow version history is retained'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_template_root_update
            BEFORE UPDATE ON tenancy_workflow_templates
            BEGIN SELECT RAISE(ABORT,'tenancy workflow template identity is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_template_root_delete
            BEFORE DELETE ON tenancy_workflow_templates
            BEGIN SELECT RAISE(ABORT,'tenancy workflow template history is retained'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_template_steps_insert
            BEFORE INSERT ON tenancy_workflow_template_steps
            WHEN (SELECT state FROM tenancy_workflow_template_versions WHERE id=NEW.version_id)<>'draft'
            BEGIN SELECT RAISE(ABORT,'published tenancy workflow steps are immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_change_frozen
            BEFORE UPDATE ON tenancy_changes WHEN
              NEW.portfolio_id IS NOT OLD.portfolio_id OR NEW.property_id IS NOT OLD.property_id OR
              NEW.unit_id IS NOT OLD.unit_id OR NEW.previous_contract_id IS NOT OLD.previous_contract_id OR
              NEW.next_contract_id IS NOT OLD.next_contract_id OR NEW.mode IS NOT OLD.mode OR
              NEW.move_out_template_version_id IS NOT OLD.move_out_template_version_id OR
              NEW.move_in_template_version_id IS NOT OLD.move_in_template_version_id OR
              NEW.created_by IS NOT OLD.created_by OR NEW.snapshot IS NOT OLD.snapshot OR
              NEW.snapshot_sha256 IS NOT OLD.snapshot_sha256 OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT,'tenancy change snapshot is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_change_delete
            BEFORE DELETE ON tenancy_changes
            BEGIN SELECT RAISE(ABORT,'tenancy change history is retained'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_step_frozen
            BEFORE UPDATE ON tenancy_workflow_step_instances WHEN
              NEW.tenancy_change_id IS NOT OLD.tenancy_change_id OR NEW.portfolio_id IS NOT OLD.portfolio_id OR
              NEW.template_step_key IS NOT OLD.template_step_key OR NEW.direction IS NOT OLD.direction OR
              NEW.title_snapshot IS NOT OLD.title_snapshot OR NEW.description_snapshot IS NOT OLD.description_snapshot OR
              NEW.requirement IS NOT OLD.requirement OR NEW.anchor IS NOT OLD.anchor OR
              NEW.offset_days IS NOT OLD.offset_days OR NEW.original_due_date IS NOT OLD.original_due_date OR
              NEW.depends_on_step_ids IS NOT OLD.depends_on_step_ids OR
              NEW.assignee_user_id IS NOT OLD.assignee_user_id OR NEW.assignee_role IS NOT OLD.assignee_role OR
              (OLD.task_id IS NOT NULL AND NEW.task_id IS NOT OLD.task_id) OR
              NEW.evidence_requirement IS NOT OLD.evidence_requirement OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT,'tenancy workflow step snapshot is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_step_delete
            BEFORE DELETE ON tenancy_workflow_step_instances
            BEGIN SELECT RAISE(ABORT,'tenancy workflow step history is retained'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_evidence_update
            BEFORE UPDATE ON tenancy_workflow_evidence_links
            BEGIN SELECT RAISE(ABORT,'tenancy workflow evidence link is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_evidence_terminal_delete
            BEFORE DELETE ON tenancy_workflow_evidence_links
            WHEN (SELECT state FROM tenancy_workflow_step_instances WHERE id=OLD.step_id)
                 IN ('completed','not_applicable')
            BEGIN SELECT RAISE(ABORT,'completed tenancy workflow evidence is retained'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_change_terminal
            BEFORE UPDATE ON tenancy_changes WHEN OLD.state IN ('completed','cancelled')
            BEGIN SELECT RAISE(ABORT,'completed tenancy change is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_tenancy_step_terminal
            BEFORE UPDATE ON tenancy_workflow_step_instances
            WHEN OLD.state IN ('completed','not_applicable')
            BEGIN SELECT RAISE(ABORT,'completed tenancy workflow step is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_handover_finalized_update
            BEFORE UPDATE ON handover_protocols WHEN OLD.status='finalized'
            BEGIN SELECT RAISE(ABORT,'finalized handover protocol is immutable'); END"""
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER IF NOT EXISTS immo_handover_finalized_delete
            BEFORE DELETE ON handover_protocols WHEN OLD.status='finalized'
            BEGIN SELECT RAISE(ABORT,'finalized handover protocol is retained'); END"""
        )
        for action, reference in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            connection.exec_driver_sql(
                f"""CREATE TRIGGER IF NOT EXISTS immo_finalized_handover_meter_{action.lower()}
                BEFORE {action} ON meter_readings
                WHEN EXISTS(SELECT 1 FROM handover_protocols
                            WHERE id={reference}.handover_id AND status='finalized')
                BEGIN SELECT RAISE(ABORT,'finalized handover meter evidence is immutable'); END"""
            )
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_tenancy_command_immutable() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'tenancy workflow command receipt is immutable'; END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_tenancy_command_immutable ON tenancy_workflow_commands")
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_tenancy_command_immutable BEFORE UPDATE OR DELETE ON tenancy_workflow_commands
            FOR EACH ROW EXECUTE FUNCTION immo_tenancy_command_immutable()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_tenancy_template_step_guard() RETURNS trigger AS $$
            DECLARE parent_id text;
            BEGIN
              IF TG_OP='INSERT' THEN
                parent_id := NEW.version_id;
              ELSE
                parent_id := OLD.version_id;
              END IF;
              IF EXISTS (SELECT 1 FROM tenancy_workflow_template_versions
                         WHERE id=parent_id AND state<>'draft') THEN
                RAISE EXCEPTION 'published tenancy workflow steps are immutable';
              END IF;
              IF TG_OP='DELETE' THEN
                RETURN OLD;
              END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_tenancy_template_step_guard ON tenancy_workflow_template_steps"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_tenancy_template_step_guard
            BEFORE INSERT OR UPDATE OR DELETE ON tenancy_workflow_template_steps
            FOR EACH ROW EXECUTE FUNCTION immo_tenancy_template_step_guard()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_tenancy_template_version_guard() RETURNS trigger AS $$
            BEGIN
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'tenancy workflow version history is retained';
              END IF;
              IF OLD.state='retired' THEN
                RAISE EXCEPTION 'retired tenancy workflow version is immutable';
              END IF;
              IF OLD.state='published' AND (
                   NEW.state<>'retired' OR
                   NEW.template_id IS DISTINCT FROM OLD.template_id OR
                   NEW.portfolio_id IS DISTINCT FROM OLD.portfolio_id OR
                   NEW.property_id IS DISTINCT FROM OLD.property_id OR
                   NEW.unit_id IS DISTINCT FROM OLD.unit_id OR
                   NEW.direction IS DISTINCT FROM OLD.direction OR
                   NEW.version IS DISTINCT FROM OLD.version OR
                   NEW.based_on_version_id IS DISTINCT FROM OLD.based_on_version_id OR
                   NEW.created_by IS DISTINCT FROM OLD.created_by OR
                   NEW.created_at IS DISTINCT FROM OLD.created_at OR
                   NEW.published_at IS DISTINCT FROM OLD.published_at
              ) THEN
                RAISE EXCEPTION 'published tenancy workflow version is immutable';
              END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_tenancy_template_version_guard ON tenancy_workflow_template_versions"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_tenancy_template_version_guard
            BEFORE UPDATE OR DELETE ON tenancy_workflow_template_versions
            FOR EACH ROW EXECUTE FUNCTION immo_tenancy_template_version_guard()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_tenancy_template_root_guard() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'tenancy workflow template identity is immutable'; END;
            $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_tenancy_template_root_guard ON tenancy_workflow_templates"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_tenancy_template_root_guard
            BEFORE UPDATE OR DELETE ON tenancy_workflow_templates
            FOR EACH ROW EXECUTE FUNCTION immo_tenancy_template_root_guard()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_tenancy_change_guard() RETURNS trigger AS $$
            BEGIN
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'tenancy change history is retained';
              END IF;
              IF OLD.state IN ('completed','cancelled') THEN
                RAISE EXCEPTION 'completed tenancy change is immutable';
              END IF;
              IF NEW.portfolio_id IS DISTINCT FROM OLD.portfolio_id OR
                 NEW.property_id IS DISTINCT FROM OLD.property_id OR
                 NEW.unit_id IS DISTINCT FROM OLD.unit_id OR
                 NEW.previous_contract_id IS DISTINCT FROM OLD.previous_contract_id OR
                 NEW.next_contract_id IS DISTINCT FROM OLD.next_contract_id OR
                 NEW.mode IS DISTINCT FROM OLD.mode OR
                 NEW.move_out_template_version_id IS DISTINCT FROM OLD.move_out_template_version_id OR
                 NEW.move_in_template_version_id IS DISTINCT FROM OLD.move_in_template_version_id OR
                 NEW.created_by IS DISTINCT FROM OLD.created_by OR
                 NEW.snapshot::text IS DISTINCT FROM OLD.snapshot::text OR
                 NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256 OR
                 NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'tenancy change snapshot is immutable';
              END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_tenancy_change_guard ON tenancy_changes")
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_tenancy_change_guard BEFORE UPDATE OR DELETE ON tenancy_changes
            FOR EACH ROW EXECUTE FUNCTION immo_tenancy_change_guard()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_tenancy_instance_guard() RETURNS trigger AS $$
            BEGIN
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'tenancy workflow step history is retained';
              END IF;
              IF OLD.state IN ('completed','not_applicable') THEN
                RAISE EXCEPTION 'completed tenancy workflow step is immutable';
              END IF;
              IF NEW.tenancy_change_id IS DISTINCT FROM OLD.tenancy_change_id OR
                 NEW.portfolio_id IS DISTINCT FROM OLD.portfolio_id OR
                 NEW.template_step_key IS DISTINCT FROM OLD.template_step_key OR
                 NEW.direction IS DISTINCT FROM OLD.direction OR
                 NEW.title_snapshot IS DISTINCT FROM OLD.title_snapshot OR
                 NEW.description_snapshot IS DISTINCT FROM OLD.description_snapshot OR
                 NEW.requirement IS DISTINCT FROM OLD.requirement OR
                 NEW.anchor IS DISTINCT FROM OLD.anchor OR
                 NEW.offset_days IS DISTINCT FROM OLD.offset_days OR
                 NEW.original_due_date IS DISTINCT FROM OLD.original_due_date OR
                 NEW.depends_on_step_ids::text IS DISTINCT FROM OLD.depends_on_step_ids::text OR
                 NEW.assignee_user_id IS DISTINCT FROM OLD.assignee_user_id OR
                 NEW.assignee_role IS DISTINCT FROM OLD.assignee_role OR
                 (OLD.task_id IS NOT NULL AND NEW.task_id IS DISTINCT FROM OLD.task_id) OR
                 NEW.evidence_requirement IS DISTINCT FROM OLD.evidence_requirement OR
                 NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'tenancy workflow step snapshot is immutable';
              END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_tenancy_instance_guard ON tenancy_workflow_step_instances"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_tenancy_instance_guard
            BEFORE UPDATE OR DELETE ON tenancy_workflow_step_instances
            FOR EACH ROW EXECUTE FUNCTION immo_tenancy_instance_guard()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_tenancy_evidence_update_guard() RETURNS trigger AS $$
            BEGIN
              IF TG_OP='UPDATE' THEN
                RAISE EXCEPTION 'tenancy workflow evidence link is immutable';
              END IF;
              IF EXISTS (SELECT 1 FROM tenancy_workflow_step_instances
                         WHERE id=OLD.step_id AND state IN ('completed','not_applicable')) THEN
                RAISE EXCEPTION 'completed tenancy workflow evidence is retained';
              END IF;
              RETURN OLD;
            END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_tenancy_evidence_update_guard ON tenancy_workflow_evidence_links"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_tenancy_evidence_update_guard
            BEFORE UPDATE OR DELETE ON tenancy_workflow_evidence_links
            FOR EACH ROW EXECUTE FUNCTION immo_tenancy_evidence_update_guard()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_handover_finalized_guard() RETURNS trigger AS $$
            BEGIN
              IF OLD.status='finalized' THEN
                RAISE EXCEPTION 'finalized handover protocol is immutable';
              END IF;
              IF TG_OP='DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_handover_finalized_guard ON handover_protocols"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_handover_finalized_guard
            BEFORE UPDATE OR DELETE ON handover_protocols
            FOR EACH ROW EXECUTE FUNCTION immo_handover_finalized_guard()"""
        )
        connection.exec_driver_sql(
            """CREATE OR REPLACE FUNCTION immo_finalized_handover_meter_guard() RETURNS trigger AS $$
            DECLARE parent_id text;
            BEGIN
              IF TG_OP='DELETE' THEN parent_id := OLD.handover_id;
              ELSE parent_id := NEW.handover_id; END IF;
              IF EXISTS (SELECT 1 FROM handover_protocols WHERE id=parent_id AND status='finalized') THEN
                RAISE EXCEPTION 'finalized handover meter evidence is immutable';
              END IF;
              IF TG_OP='DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql"""
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_finalized_handover_meter_guard ON meter_readings"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER immo_finalized_handover_meter_guard
            BEFORE INSERT OR UPDATE OR DELETE ON meter_readings
            FOR EACH ROW EXECUTE FUNCTION immo_finalized_handover_meter_guard()"""
        )


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
