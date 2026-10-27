"""Operations overview: full backups, restore probes, secrets at rest, schema state.

Installation-wide by nature: restricted portfolio accounts are refused (403), here and
already by the portfolio middleware for /admin.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require_role
from ..models import UserRead
from ..services import full_backup
from ..services.integrations.manager import integration_manager
from ..services.portfolio_scope import require_installation_scope

router = APIRouter(prefix="/admin/operations", tags=["Admin"])


@router.get("/platform")
def platform_status(actor: UserRead = Depends(require_role("eigentuemer"))):
    require_installation_scope()
    from sqlalchemy import select

    from ..config import SETTING_ORIGINS, settings
    from ..db.access_models import PluginInstallationORM
    from ..db.session import SessionLocal
    from ..plugins import get_plugin_errors, get_plugins
    from ..plugins.lifecycle import manifest
    with SessionLocal() as session:
        rows = {row.name: row for row in session.scalars(select(PluginInstallationORM))}
        plugins = []
        for plugin in get_plugins():
            row = rows.get(plugin.name)
            plugins.append({**plugin.to_dict(), "declaration": manifest(plugin),
                            "revision": row.revision if row else 0,
                            "installed_version": row.manifest.get("version") if row else None,
                            "enabled": row.enabled if row else False,
                            "backup_revisions": [item["revision"] for item in row.backups] if row else []})
    return {"storage": {"backend": settings.file_storage_backend,
                        "origin": SETTING_ORIGINS.get("file_storage_backend", "default")},
            "portable_export": {"passphrase_configured": bool(settings.backup_passphrase),
                                "application_gate": "separate_owned_probe_required"},
            "plugins": plugins, "plugin_errors": get_plugin_errors(), "sandboxed": False}


class PluginChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str = Field(pattern="^(upgrade|uninstall|restore)$")
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)
    backup_revision: int | None = Field(default=None, ge=1)


@router.post("/plugins/{name}")
def change_plugin(name: str, payload: PluginChange, actor: UserRead = Depends(require_role("eigentuemer"))):
    require_installation_scope()
    _require_database()
    from ..db.session import SessionLocal
    from ..plugins import get_plugins, stop_plugins
    from ..plugins.lifecycle import change
    plugin = next((candidate for candidate in get_plugins() if candidate.name == name), None)
    if plugin is None:
        raise HTTPException(404, "Geprüftes Pluginpaket ist nicht installiert")
    try:
        result = change(SessionLocal, plugin, actor_id=actor.id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    # Existing routes cannot keep serving code against a changed or uninstalled schema.
    from ..app import app
    stop_plugins(app, [plugin])
    return result


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


class SecondTargetRequest(BaseModel):
    path: str = Field("", max_length=600)


@router.put("/second-target")
def set_second_target(payload: SecondTargetRequest) -> dict:
    """Owner only: the folder every full backup is copied to (USB drive, NAS); empty removes it.

    The folder is created and a test file written before it is kept; the next full backup
    copies its archive there and checks the copy.
    """
    require_installation_scope()
    try:
        return full_backup.set_second_target(payload.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except OSError as exc:
        raise HTTPException(503, f"Einstellung nicht gespeichert: {exc.strerror or type(exc).__name__}") from None


@router.post("/restore-probe")
def run_restore_probe() -> dict:
    """Restore the newest archive into an isolated directory, check it, delete it."""
    require_installation_scope()
    _require_database()
    try:
        return full_backup.restore_probe()
    except Exception as exc:     # logged in the ops log by restore_probe
        raise _failed(exc) from None
