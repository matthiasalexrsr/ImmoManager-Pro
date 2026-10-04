"""Shared frozen workflow/evidence guards for migrations and local startup."""

from typing import cast

from sqlalchemy import Table

from .tenancy_workflow_models import TENANCY_WORKFLOW_MODELS


def ensure_tenancy_workflow_schema(connection):
    for model in TENANCY_WORKFLOW_MODELS:
        cast(Table, model.__table__).create(connection, checkfirst=True)
    install_guards(connection)


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_tenancy_template_steps_{action.lower()}")
            target = " OR (SELECT state FROM tenancy_workflow_template_versions WHERE id=NEW.version_id)<>'draft'" if action == "UPDATE" else ""
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS immo_tenancy_commands_{action.lower()} "
                f"BEFORE {action} ON tenancy_workflow_commands BEGIN "
                "SELECT RAISE(ABORT,'tenancy workflow command receipt is immutable'); END"
            )
            connection.exec_driver_sql(
                f"""CREATE TRIGGER IF NOT EXISTS immo_tenancy_template_steps_{action.lower()}
                BEFORE {action} ON tenancy_workflow_template_steps
                WHEN (SELECT state FROM tenancy_workflow_template_versions WHERE id=OLD.version_id)<>'draft'{target}
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
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_finalized_handover_meter_{action.lower()}")
            parents = "(OLD.handover_id, NEW.handover_id)" if action == "UPDATE" else f"({reference}.handover_id)"
            connection.exec_driver_sql(
                f"""CREATE TRIGGER IF NOT EXISTS immo_finalized_handover_meter_{action.lower()}
                BEFORE {action} ON meter_readings
                WHEN EXISTS(SELECT 1 FROM handover_protocols
                            WHERE id IN {parents} AND status='finalized')
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
            DECLARE parent_ids text[];
            BEGIN
              IF TG_OP='INSERT' THEN
                parent_ids := ARRAY[NEW.version_id];
              ELSIF TG_OP='UPDATE' THEN
                parent_ids := ARRAY[OLD.version_id, NEW.version_id];
              ELSE
                parent_ids := ARRAY[OLD.version_id];
              END IF;
              PERFORM 1 FROM tenancy_workflow_template_versions WHERE id=ANY(parent_ids) ORDER BY id FOR UPDATE;
              IF EXISTS (SELECT 1 FROM tenancy_workflow_template_versions
                         WHERE id=ANY(parent_ids) AND state<>'draft') THEN
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
            DECLARE parent_ids text[];
            BEGIN
              IF TG_OP='DELETE' THEN parent_ids := ARRAY[OLD.handover_id];
              ELSIF TG_OP='INSERT' THEN parent_ids := ARRAY[NEW.handover_id];
              ELSE parent_ids := ARRAY[OLD.handover_id, NEW.handover_id]; END IF;
              PERFORM 1 FROM handover_protocols WHERE id=ANY(parent_ids) ORDER BY id FOR UPDATE;
              IF EXISTS (SELECT 1 FROM handover_protocols WHERE id=ANY(parent_ids) AND status='finalized') THEN
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
