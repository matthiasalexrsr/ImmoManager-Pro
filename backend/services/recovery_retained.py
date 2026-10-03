"""Retained workflow/job boundaries for business-subset transfer and reset."""

from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from .operational_job_validation import TABLES as JOB_TABLES
from .operational_scheduler_validation import TABLE as SCHEDULER_TABLE
from .tenancy_workflow_validation import TABLES as WORKFLOW_TABLES

TABLES = frozenset(JOB_TABLES) | WORKFLOW_TABLES | {SCHEDULER_TABLE}
MESSAGE = "Gespeicherte Mieterwechsel- oder Arbeitslistenhistorie wird durch diese Teiloperation nicht übertragen. Vollständige Offline-Sicherung/Wiederherstellung verwenden."


def guard_operational_history(store, *, serialized=False):
    """Refuse before destructive DML, and recheck behind the shared writer fence."""
    from ..storage import ValidationError
    if not hasattr(store, "db"):
        if any(store.__dict__.get(name) for name in TABLES):
            raise ValidationError(MESSAGE)
        return
    db = store.db
    names = set(inspect(db.get_bind()).get_table_names())
    for family in (set(JOB_TABLES), WORKFLOW_TABLES):
        if names & family and not family <= names:
            raise ValidationError("Unvollständige Mieterwechsel-/Arbeitslistentabellen. Teiloperation vor Datenänderung abgebrochen.")
    if not names & TABLES:
        return
    if serialized:
        from .contract_occupancy import begin_writer
        begin_writer(db)
        if db.get_bind().dialect.name == "postgresql":
            # Writers take account management -> operational/domain locks. Take
            # the account barrier first; never wait child-first on their parent.
            if "auth_setup" in names:
                db.connection().exec_driver_sql('LOCK TABLE "auth_setup" IN SHARE ROW EXCLUSIVE MODE')
            parents = ("operational_lock", "users", "tenants", "documents", "properties", "units", "contracts",
                       "tasks", "handover_protocols", "meter_readings", "rent_charges", "receivables", "calendar_events", "notifications")
            try:
                # Include domain parents BEFORE children, even for the supported
                # SQL-store/Memory-auth test mode. NOWAIT avoids an inversion with
                # a writer paused before its first workflow INSERT or late FK.
                # A connection savepoint preserves a caller transaction on busy.
                with db.connection().begin_nested():
                    for name in (*parents, *sorted(TABLES)):
                        if name in names:
                            db.connection().exec_driver_sql('LOCK TABLE "' + name + '" IN EXCLUSIVE MODE NOWAIT')
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) != "55P03":
                    raise
                raise ValidationError("Ein laufender Schreibvorgang verhindert den sicheren Reset/Teilimport. Nach dessen Abschluss erneut versuchen.") from None
    with db.no_autoflush:
        pending = any(getattr(getattr(row, "__table__", None), "name", None) in TABLES for row in db.new | db.dirty | db.deleted)
        retained = pending or any(db.execute(text('SELECT 1 FROM "' + name + '" LIMIT 1')).first() is not None for name in sorted(TABLES & names))
    if retained:
        raise ValidationError(MESSAGE)
