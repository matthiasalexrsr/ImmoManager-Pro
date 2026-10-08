"""Operations overview: full backups, restore probes, secrets at rest, schema state.

Installation-wide by nature: restricted portfolio accounts are refused (403), here and
already by the portfolio middleware for /admin.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from ..services import full_backup
from ..services.integrations.manager import integration_manager
from ..services.portfolio_scope import require_installation_scope

router = APIRouter(prefix="/admin/operations", tags=["Admin"])


def _require_database() -> None:
    from .. import dependencies

    if dependencies._scoped_session is None:
        raise HTTPException(409, "Speicher-Modus ohne Datenbank: kein Vollbackup möglich. JSON-Export verwenden.")


def _schema() -> dict[str, Any] | None:
    from .. import dependencies

    if dependencies._scoped_session is None:
        return None
    from ..db.schema_state import inspect_engine
    from ..db.session import engine

    return inspect_engine(engine).as_dict()


def _jobs() -> list[dict[str, Any]]:
    from ..services.jobs.scheduler import BACKUP_KIND, PROBE_KIND, get_job_store

    runs = [run for run in get_job_store().list_runs(limit=200) if run.kind in (BACKUP_KIND, PROBE_KIND)]
    return [{"kind": run.kind, "key": run.idempotency_key, "status": run.status, "attempts": run.attempts,
             "last_error": run.last_error, "created_at": run.created_at, "finished_at": run.finished_at}
            for run in runs[:10]]


def _failed(exc: Exception) -> HTTPException:
    from ..services.document_version_validation import ArchiveIntegrityError
    from ..services.secret_box import SecretError

    # own messages (no paths of secrets, no values) are shown; anything else only by type
    if isinstance(exc, (full_backup.BackupError, SecretError, ArchiveIntegrityError)):
        return HTTPException(409, str(exc))
    return HTTPException(503, f"Sicherung nicht möglich: {type(exc).__name__}")


@router.get("")
def operations_overview() -> dict:
    require_installation_scope()
    return full_backup.overview(secret_status=integration_manager.secret_status(), schema=_schema(), jobs=_jobs())


@router.post("/backup")
def run_full_backup() -> dict:
    """Full backup now (database, uploads, configuration, keys); verified before it is kept."""
    require_installation_scope()
    _require_database()
    try:
        return full_backup.create_full_backup("manual")
    except Exception as exc:     # logged in the ops log by create_full_backup
        raise _failed(exc) from None


@router.post("/restore-probe")
def run_restore_probe() -> dict:
    """Restore the newest archive into an isolated directory, check it, delete it."""
    require_installation_scope()
    _require_database()
    try:
        return full_backup.restore_probe()
    except Exception as exc:     # logged in the ops log by restore_probe
        raise _failed(exc) from None
