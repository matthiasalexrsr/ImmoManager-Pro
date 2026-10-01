"""Self-update engine for ImmoManager Pro.

Checks GitHub for new releases, downloads and applies updates via git,
runs database migrations, and can roll back on failure.

Updates check every install/build/migration result and preserve the previous
frontend. SQLite snapshots use the online backup API. Restoring a database is
restricted to an explicitly offline operation: this module has no server
maintenance gate or restart supervisor. Incomplete recovery is reported honestly.

This module is designed for the standard Python/uvicorn deployment.
Docker and PyInstaller deployments should use their native update mechanisms.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url

from .config import settings
from .frontend_build import FrontendBuildError, ensure_frontend, promote_dist, validate_dist

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RUNTIME_DIR = Path(settings.data_dir).expanduser().resolve() if settings.data_dir else _PROJECT_ROOT
_BACKUP_DIR = Path(settings.backup_dir).expanduser().resolve() if settings.backup_dir else _RUNTIME_DIR / "backups"
_UPDATE_DIR = _RUNTIME_DIR / ".updates"
_LOCK_FILE = _UPDATE_DIR / "update.lock"
_HISTORY_FILE = _UPDATE_DIR / "history.json"
_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"
_lock_token: str | None = None

# Timeout for GitHub API requests
_HTTP_TIMEOUT = 30.0


# ─── Version Comparison ──────────────────────────────────────────────────────

def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a semver string like '1.2.3' into a comparable tuple."""
    cleaned = version_str.lstrip("vV").strip()
    parts = []
    for part in cleaned.split("."):
        try:
            parts.append(int(part.split("-")[0].split("+")[0]))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer_version(remote: str, local: str) -> bool:
    """Return True if `remote` is strictly newer than `local`."""
    return _parse_version(remote) > _parse_version(local)


# ─── Lock Management ─────────────────────────────────────────────────────────

def _acquire_lock() -> bool:
    """Try to acquire the update lock.  Returns False if already locked."""
    global _lock_token
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    # Never steal an update lock on elapsed time alone; a slow install may still
    # be running. A crashed process requires deliberate removal of its lock.
    try:
        descriptor = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    token = uuid4().hex
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps({"locked_at": datetime.now(timezone.utc).isoformat(),
                                "pid": os.getpid(), "token": token}))
    _lock_token = token
    return True


def _release_lock() -> None:
    """Release the update lock."""
    global _lock_token
    try:
        if _lock_token and json.loads(_LOCK_FILE.read_text(encoding="utf-8")).get("token") == _lock_token:
            _LOCK_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("Update lock could not be released", exc_info=True)
    finally:
        _lock_token = None


def is_update_locked() -> bool:
    """Check whether an update is currently in progress."""
    return _LOCK_FILE.exists()


# ─── Git Helpers ──────────────────────────────────────────────────────────────

def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + list(args)
    try:
        return subprocess.run(cmd, cwd=cwd or _PROJECT_ROOT, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=f"Git fehlgeschlagen: {type(exc).__name__}")


def _is_git_repo() -> bool:
    """Check whether the project root is a git repository."""
    result = _run_git("rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _get_current_commit() -> str | None:
    """Return the current HEAD commit hash."""
    result = _run_git("rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _get_current_branch() -> str | None:
    """Return the current git branch name."""
    result = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _has_uncommitted_changes() -> bool:
    """Check for uncommitted changes in the working tree."""
    result = _run_git("status", "--porcelain", "--", ".", *_runtime_excludes())
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def _runtime_excludes() -> list[str]:
    excluded = {".updates", "backups", "frontend/dist"}
    root = _PROJECT_ROOT.resolve()
    for path in (_UPDATE_DIR, _BACKUP_DIR, Path(settings.data_dir) if settings.data_dir else root):
        resolved = path.resolve()
        if resolved != root and resolved.is_relative_to(root):
            excluded.add(resolved.relative_to(root).as_posix())
    return [f":(exclude,literal){path}" for path in sorted(excluded)]


def _stash_changes() -> bool:
    """Stash any uncommitted changes.  Returns True if something was stashed."""
    if not _has_uncommitted_changes():
        return False
    previous_stash = _run_git("rev-parse", "--verify", "refs/stash").stdout.strip()
    result = _run_git("stash", "push", "--include-untracked", "-m",
                      f"ImmoManager auto-stash before update {datetime.now(timezone.utc).isoformat()}",
                      "--", ".", *_runtime_excludes())
    if result.returncode:
        raise RuntimeError("Lokale Änderungen konnten nicht gesichert werden")
    if _run_git("rev-parse", "--verify", "refs/stash").stdout.strip() == previous_stash:
        return False
    return True


def _stash_pop() -> bool:
    """Restore stashed changes."""
    result = _run_git("stash", "pop")
    return result.returncode == 0


# ─── GitHub API ───────────────────────────────────────────────────────────────

def check_for_updates() -> dict:
    """Query GitHub for available updates.

    Returns a dict with:
      - update_available: bool
      - current_version: str
      - latest_version: str (if available)
      - release_notes: str (if available)
      - release_url: str (if available)
      - published_at: str (if available)
      - error: str (if check failed)
      - is_git_repo: bool
      - update_channel: str
    """
    current = settings.app_version
    repo_url = settings.update_repo_url
    channel = settings.update_channel

    result = {
        "update_available": False,
        "current_version": current,
        "latest_version": None,
        "release_notes": None,
        "release_url": None,
        "published_at": None,
        "error": None,
        "is_git_repo": _is_git_repo(),
        "update_channel": channel,
        "is_frozen": getattr(sys, "frozen", False),
        "live_apply_supported": False,
        "maintenance_hint": "Anwendung stoppen und den Offline-Updateweg verwenden: python -m backend.maintenance --offline --data-dir <Datenordner>",
    }

    if not repo_url:
        result["error"] = "Kein GitHub-Repository konfiguriert (UPDATE_REPO_URL)"
        return result

    if getattr(sys, "frozen", False):
        result["error"] = "Updates sind im PyInstaller-Bundle nicht verfügbar. Bitte neue Version herunterladen."
        return result

    # Extract owner/repo from URL
    owner_repo = _extract_owner_repo(repo_url)
    if not owner_repo:
        result["error"] = f"Ungültige Repository-URL: {repo_url}"
        return result

    try:
        if channel == "stable":
            api_url = f"https://api.github.com/repos/{owner_repo}/releases/latest"
        else:
            # Include pre-releases — get all and pick the newest
            api_url = f"https://api.github.com/repos/{owner_repo}/releases?per_page=5"

        headers = {"Accept": "application/vnd.github+json"}
        if settings.update_github_token:
            headers["Authorization"] = f"Bearer {settings.update_github_token}"

        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(api_url, headers=headers)

        if resp.status_code == 404:
            result["error"] = "Repository oder Releases nicht gefunden"
            return result

        if resp.status_code == 403:
            result["error"] = "GitHub API Rate-Limit erreicht. Bitte später erneut versuchen."
            return result

        resp.raise_for_status()
        data = resp.json()

        if channel == "stable":
            release = data
        else:
            # data is a list; pick the first (newest)
            if not data:
                result["error"] = "Keine Releases gefunden"
                return result
            release = data[0]

        tag = release.get("tag_name", "")
        result["latest_version"] = tag.lstrip("vV")
        result["release_notes"] = release.get("body", "")
        result["release_url"] = release.get("html_url", "")
        result["published_at"] = release.get("published_at", "")
        result["update_available"] = is_newer_version(tag, current)

    except httpx.TimeoutException:
        result["error"] = "Zeitüberschreitung bei der Verbindung zu GitHub"
    except httpx.HTTPStatusError as exc:
        result["error"] = f"GitHub API Fehler: HTTP {exc.response.status_code}"
    except Exception as exc:
        logger.exception("Update check failed")
        result["error"] = f"Prüfung fehlgeschlagen: {exc}"

    return result


def _extract_owner_repo(url: str) -> str | None:
    """Extract 'owner/repo' from various GitHub URL formats.

    Only accepts valid GitHub owner/repo patterns to prevent SSRF or
    injection via crafted repository URLs.
    """
    url = url.strip().rstrip("/").removesuffix(".git")
    # https://github.com/owner/repo or git@github.com:owner/repo
    if "github.com" not in url:
        return None
    parts = url.split("github.com")[-1].lstrip(":/").split("/")
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    # Validate owner/repo contain only safe characters
    _SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
    if not _SAFE_RE.match(owner) or not _SAFE_RE.match(repo):
        logger.warning("Rejected unsafe owner/repo pattern: %s/%s", owner, repo)
        return None
    return f"{owner}/{repo}"


# ─── Data Backup ──────────────────────────────────────────────────────────────

def _create_pre_update_backup() -> str | None:
    """Create a full data backup before updating.

    Returns the backup filename on success, None on failure.
    """
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"pre_update_{timestamp}.json"
    backup_path = _BACKUP_DIR / backup_name

    try:

        # Use the same export logic as admin.py
        from .routers.admin import _export_store_data
        data = _export_store_data()
        data["_meta"] = {
            "type": "pre_update_backup",
            "version": settings.app_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "commit": _get_current_commit(),
        }

        content = json.dumps(data, ensure_ascii=False, indent=2)
        backup_path.write_text(content, encoding="utf-8")

        # Write checksum for integrity verification
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        checksum_path = backup_path.with_suffix(".json.sha256")
        checksum_path.write_text(checksum, encoding="utf-8")

        # Verify backup is readable and non-empty
        verify = json.loads(backup_path.read_text(encoding="utf-8"))
        if not verify or not verify.get("_meta"):
            logger.error("Backup verification failed: missing _meta")
            return None

        logger.info("Pre-update backup created: %s (sha256: %s)", backup_name, checksum[:16])
        return backup_name
    except Exception:
        logger.exception("Failed to create pre-update backup")
        return None


def _create_db_snapshot() -> str | None:
    """Snapshot committed SQLite data, including uncheckpointed WAL pages."""
    db_path = _sqlite_database_path()
    if db_path is None or not db_path.is_file():
        return None
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_name = f"pre_update_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.db"
    snapshot_path = _BACKUP_DIR / snapshot_name
    try:
        with closing(sqlite3.connect(_readonly_uri(db_path), uri=True, timeout=10)) as source:
            with closing(sqlite3.connect(snapshot_path, timeout=10)) as destination:
                _sqlite_backup(source, destination)
                _verify_sqlite(destination)
        snapshot_path.with_suffix(".db.sha256").write_text(_file_checksum(snapshot_path), encoding="ascii")
        logger.info("Database snapshot created: %s", snapshot_name)
        return snapshot_name
    except Exception:
        logger.exception("Failed to create database snapshot")
        snapshot_path.unlink(missing_ok=True)
        return None


def _sqlite_database_path() -> Path | None:
    url = make_url(settings.database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def _readonly_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_sqlite(connection) -> None:
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RuntimeError("SQLite integrity verification failed")


def _sqlite_backup(source, destination) -> None:
    deadline = time.monotonic() + 60
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup exceeded 60 seconds")
    source.backup(destination, pages=100, progress=progress, sleep=0.1)


# ─── Migration ────────────────────────────────────────────────────────────────

def _run_migrations() -> tuple[bool, str]:
    """Run Alembic migrations.  Returns (success, message)."""
    try:
        # A subprocess loads the updated files/dependencies instead of modules
        # cached by the running server, and cannot change its logging config.
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(_PROJECT_ROOT / "alembic.ini"), "upgrade", "head"],
            cwd=_PROJECT_ROOT, env={**os.environ, "DATABASE_URL": settings.database_url},
            capture_output=True, text=True, timeout=300,
        )
        if completed.returncode:
            return False, "Migrationen fehlgeschlagen (Exit %s)" % completed.returncode
        return True, "Migrationen erfolgreich angewendet"
    except Exception as exc:
        logger.exception("Migration failed during update")
        return False, f"Migration fehlgeschlagen: {exc}"


# ─── Frontend Rebuild ─────────────────────────────────────────────────────────

def _rebuild_frontend() -> tuple[bool, str]:
    """Build only if stale; missing npm is an error when assets need rebuilding."""
    try:
        return True, ensure_frontend(_PROJECT_ROOT)
    except (FrontendBuildError, OSError) as exc:
        return False, str(exc)


def _install_dependencies() -> tuple[bool, str]:
    try:
        for arguments in (("install", "-r", str(_PROJECT_ROOT / "requirements.txt"), "-q"), ("check",)):
            completed = subprocess.run([sys.executable, "-m", "pip", *arguments], cwd=_PROJECT_ROOT,
                                       capture_output=True, text=True, timeout=300)
            if completed.returncode:
                return False, f"Python-Abhängigkeiten fehlgeschlagen (Exit {completed.returncode})"
        return True, "Python-Abhängigkeiten installiert und geprüft"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Python-Abhängigkeiten fehlgeschlagen: {type(exc).__name__}"


# ─── Update History ──────────────────────────────────────────────────────────

def _load_history() -> list[dict]:
    """Load the update history from disk."""
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Could not load update history file", exc_info=True)
        return []


def _save_history(history: list[dict]) -> None:
    """Save the update history to disk."""
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _record_update(entry: dict) -> None:
    """Append an entry to the update history."""
    history = _load_history()
    history.append(entry)
    # Keep last 50 entries
    if len(history) > 50:
        history = history[-50:]
    _save_history(history)


def get_update_history() -> list[dict]:
    """Return the update history, newest first."""
    return list(reversed(_load_history()))


# ─── Core Update Logic ───────────────────────────────────────────────────────

def _capture_frontend() -> Path | None:
    if not _FRONTEND_DIST.exists():
        return None
    validate_dist(_FRONTEND_DIST)
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(prefix="frontend-before-", dir=_UPDATE_DIR))
    try:
        shutil.copytree(_FRONTEND_DIST, saved / "dist")
    except Exception:
        _remove_frontend_capture(saved)
        raise
    return saved


def _restore_frontend(saved: Path | None) -> bool:
    if saved is None:
        return False
    staged = None
    try:
        staged = Path(tempfile.mkdtemp(prefix=".immomanager-build-", dir=_FRONTEND_DIST.parent))
        shutil.copytree(saved / "dist", staged, dirs_exist_ok=True)
        promote_dist(staged, _FRONTEND_DIST.parent)
        return True
    except (OSError, FrontendBuildError):
        logger.exception("Previous frontend could not be restored")
        return False
    finally:
        if staged and staged.exists() and staged.resolve().parent == _FRONTEND_DIST.parent.resolve() and not staged.is_symlink():
            try:
                shutil.rmtree(staged)
            except OSError:
                logger.warning("Frontend restore staging could not be removed", exc_info=True)


def _remove_frontend_capture(saved: Path | None) -> None:
    if saved and not saved.is_symlink() and saved.resolve().parent == _UPDATE_DIR.resolve() and saved.name.startswith("frontend-before-"):
        shutil.rmtree(saved)


def _code_version() -> str:
    import tomllib
    with (_PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def configure_runtime_paths() -> None:
    """Refresh runtime paths after the offline CLI loads its data-directory config."""
    global _RUNTIME_DIR, _BACKUP_DIR, _UPDATE_DIR, _LOCK_FILE, _HISTORY_FILE
    _RUNTIME_DIR = Path(settings.data_dir).expanduser().resolve() if settings.data_dir else _PROJECT_ROOT
    _BACKUP_DIR = Path(settings.backup_dir).expanduser().resolve() if settings.backup_dir else _RUNTIME_DIR / "backups"
    _UPDATE_DIR = _RUNTIME_DIR / ".updates"
    _LOCK_FILE = _UPDATE_DIR / "update.lock"
    _HISTORY_FILE = _UPDATE_DIR / "history.json"


def apply_update(target_version: str | None = None, *, offline: bool = False) -> dict:
    """Apply verified updates. Offline restoration requires a stopped application.

    HTTP callers always leave offline=False. This updater has no supervisor or
    maintenance gate, so it cannot safely overwrite their live database.
    """
    result: dict[str, Any] = {
        "success": False, "message": "", "steps": [], "restart_required": False,
        "backup_name": None, "previous_version": settings.app_version, "new_version": None,
        "rollback_performed": False, "rollback_completed": False, "startup_ready": False,
        "manual_recovery_required": False, "database_restore_required": False,
        "frontend_restore_required": False, "frontend_backup_name": None,
        "offline_update_required": False,
    }
    if getattr(sys, "frozen", False):
        result["message"] = "Updates sind im PyInstaller-Bundle nicht verfügbar"
        return result
    if settings.is_production and not settings.update_allow_in_production:
        result["message"] = "Updates sind in der Produktionsumgebung deaktiviert"
        return result
    if not _is_git_repo():
        result["message"] = "Kein Git-Repository. Updates erfordern eine Git-Installation."
        return result
    if not settings.update_repo_url:
        result["message"] = "Kein Update-Repository konfiguriert"
        return result
    if target_version and not re.fullmatch(r"\d+\.\d+\.\d+([a-zA-Z0-9._-]*)?", target_version.lstrip("vV").strip()):
        result["message"] = "Ungültiges Versionsformat"
        return result
    if not offline:
        result["offline_update_required"] = True
        result["message"] = ("Updates mit Datenbank-Migrationen erfordern eine gestoppte Anwendung. "
                             "Bitte den Offline-Updateweg verwenden: python -m backend.maintenance --offline --data-dir <Datenordner>")
        return result
    if not _acquire_lock():
        result["message"] = "Ein Update läuft bereits"
        return result

    previous_commit = _get_current_commit()
    stashed = False
    code_changed = False
    dependencies_started = False
    migration_started = False
    db_snapshot = None
    saved_frontend = None
    try:
        if not previous_commit:
            raise RuntimeError("Vorheriger Commit konnte nicht ermittelt werden")
        branch = _get_current_branch()
        if not target_version and (not branch or branch == "HEAD"):
            raise RuntimeError("Bitte eine konkrete Update-Version für diesen detached HEAD wählen")
        result["steps"].append("Erstelle Datensicherung...")
        backup_name = _create_pre_update_backup()
        if not backup_name:
            raise RuntimeError("Datensicherung fehlgeschlagen")
        result["backup_name"] = backup_name
        result["steps"].append(f"Backup erstellt: {backup_name}")
        db_snapshot = _create_db_snapshot()
        if make_url(settings.database_url).drivername.startswith("sqlite") and not db_snapshot:
            raise RuntimeError("SQLite-Snapshot fehlgeschlagen; Update wurde vor Änderungen abgebrochen")
        if db_snapshot:
            result["steps"].append(f"Datenbank-Snapshot erstellt: {db_snapshot}")
        saved_frontend = _capture_frontend()
        stashed = _stash_changes()
        if stashed:
            result["steps"].append("Lokale Änderungen einschließlich unversionierter Dateien gesichert")
        fetch = _run_git("fetch", "--tags", "origin", *([branch] if branch and branch != "HEAD" else []))
        if fetch.returncode:
            raise RuntimeError("Git fetch fehlgeschlagen")
        code_changed = True
        if target_version:
            tag = target_version if target_version.startswith("v") else f"v{target_version}"
            checkout = _run_git("checkout", tag)
            if checkout.returncode:
                checkout = _run_git("checkout", target_version)
            if checkout.returncode:
                raise RuntimeError("Gewählte Version wurde nicht gefunden")
        else:
            merged = _run_git("merge", f"origin/{branch}", "--ff-only")
            if merged.returncode:
                raise RuntimeError("Git-Update kann nicht als Fast-Forward angewendet werden")
        new_commit = _get_current_commit()
        if not new_commit:
            raise RuntimeError("Aktualisierter Commit konnte nicht ermittelt werden")
        if new_commit == previous_commit:
            code_changed = False
            if stashed and not _stash_pop():
                raise RuntimeError("Lokale Änderungen konnten nicht wiederhergestellt werden")
            stashed = False
            frontend_ok, frontend_message = _rebuild_frontend()
            result["steps"].append(frontend_message)
            if not frontend_ok:
                raise RuntimeError("Code ist aktuell; das Frontend ist nicht startbereit")
            result.update(success=True, message="Bereits auf dem neuesten Stand", startup_ready=True)
            return result

        dependencies_started = True
        dependency_ok, dependency_message = _install_dependencies()
        result["steps"].append(dependency_message)
        if not dependency_ok:
            raise RuntimeError("Installation der Python-Abhängigkeiten fehlgeschlagen")
        # Build first, so missing npm or compile errors cannot leave a migrated DB.
        frontend_ok, frontend_message = _rebuild_frontend()
        result["steps"].append(frontend_message)
        if not frontend_ok:
            raise RuntimeError("Frontend-Build fehlgeschlagen")
        migration_started = True
        migration_ok, migration_message = _run_migrations()
        result["steps"].append(migration_message)
        if not migration_ok:
            raise RuntimeError("Datenbank-Migration fehlgeschlagen")
        version = _code_version()
        if stashed:
            if not _stash_pop():
                raise RuntimeError("Lokale Änderungen konnten nicht wiederhergestellt werden; Stash bleibt erhalten")
            stashed = False
            result["steps"].append("Lokale Änderungen wiederhergestellt")
        result.update(success=True, restart_required=True, startup_ready=True, new_version=version,
                      message=f"Update auf {version} geprüft. Bitte die Anwendung manuell neu starten.")
        result["steps"].append("Installation, Frontend und Migration erfolgreich; manueller Neustart erforderlich")
        try:
            _record_update({"timestamp": datetime.now(timezone.utc).isoformat(), "from_version": settings.app_version,
                            "to_version": version, "from_commit": previous_commit, "to_commit": new_commit,
                            "backup": backup_name, "db_snapshot": db_snapshot, "success": True})
        except OSError:
            logger.exception("Update history could not be written")
            result["steps"].append("Update-Historie konnte nicht gespeichert werden")
    except Exception as exc:
        logger.exception("Update failed")
        result["message"] = str(exc) if isinstance(exc, RuntimeError) else f"Update fehlgeschlagen: {type(exc).__name__}"
        if code_changed or stashed or dependencies_started:
            _rollback(previous_commit, stashed, result, reset_code=code_changed,
                      restore_dependencies=dependencies_started, saved_frontend=saved_frontend,
                      db_snapshot=db_snapshot if migration_started else None,
                      database_touched=migration_started, offline=offline)
            if result["manual_recovery_required"]:
                result["message"] += ". Wiederherstellung ist unvollständig; Anwendung stoppen und manuell prüfen."
        else:
            result["steps"].append("Update vor Änderungen abgebrochen")
        try:
            _record_update({"timestamp": datetime.now(timezone.utc).isoformat(), "from_version": settings.app_version,
                            "backup": result["backup_name"], "db_snapshot": db_snapshot, "success": False,
                            "rollback_completed": result["rollback_completed"], "message": result["message"]})
        except OSError:
            logger.exception("Failed update history could not be written")
    finally:
        try:
            if saved_frontend and result["frontend_restore_required"]:
                result["frontend_backup_name"] = saved_frontend.name
                result["steps"].append(f"Vorherige Frontend-Dateien bleiben für die Wiederherstellung erhalten: {saved_frontend.name}")
            else:
                _remove_frontend_capture(saved_frontend)
        except OSError:
            logger.warning("Temporary frontend capture could not be removed", exc_info=True)
        _release_lock()
    return result


def _rollback(previous_commit: str | None, stashed: bool, result: dict, *, reset_code: bool = True,
              restore_dependencies: bool = False, saved_frontend: Path | None = None,
              db_snapshot: str | None = None, database_touched: bool = False, offline: bool = False) -> None:
    code_ok = not reset_code
    if reset_code and previous_commit:
        reset = _run_git("reset", "--hard", previous_commit)
        code_ok = reset.returncode == 0
        result["rollback_performed"] = code_ok
        result["steps"].append("Vorherigen Code wiederhergestellt" if code_ok else "Code-Rollback fehlgeschlagen")
    elif reset_code:
        result["steps"].append("Rollback nicht möglich: vorheriger Commit unbekannt")
    stash_ok = not stashed or _stash_pop()
    if not stash_ok:
        result["steps"].append("Lokale Änderungen verbleiben im Git-Stash und müssen manuell geprüft werden")
    dependencies_ok = True
    if restore_dependencies:
        dependencies_ok, message = _install_dependencies()
        result["steps"].append("Vorherige Abhängigkeiten: " + message)
    frontend_ok = True
    if saved_frontend:
        frontend_ok = _restore_frontend(saved_frontend)
        result["steps"].append("Vorheriges Frontend wiederhergestellt" if frontend_ok else "Frontend-Rollback fehlgeschlagen")
    elif restore_dependencies:
        frontend_ok = False
        result["steps"].append("Kein vorheriges Frontend vorhanden; passender Build erforderlich")
    result["frontend_restore_required"] = not frontend_ok
    database_ok = not database_touched
    if database_touched:
        database_ok = bool(db_snapshot and _restore_db_snapshot(db_snapshot, offline=offline))
        result["database_restore_required"] = not database_ok
        result["steps"].append("Datenbank-Snapshot geprüft und wiederhergestellt" if database_ok else
                               "Datenbank nicht automatisch wiederhergestellt; Anwendung stoppen und Snapshot manuell zurückspielen")
    complete = code_ok and stash_ok and dependencies_ok and frontend_ok and database_ok
    result.update(rollback_completed=complete, startup_ready=complete, manual_recovery_required=not complete,
                  restart_required=restore_dependencies)


def _restore_db_snapshot(snapshot_name: str, *, offline: bool = False) -> bool:
    """Restore via SQLite's backup API only after the application was stopped."""
    if not offline:
        logger.error("Refusing to overwrite a live database without a maintenance gate")
        return False
    db_path = _sqlite_database_path()
    snapshot_path = _BACKUP_DIR / snapshot_name
    if db_path is None or snapshot_path.is_symlink() or snapshot_path.resolve().parent != _BACKUP_DIR.resolve() or not snapshot_path.is_file():
        return False
    try:
        if snapshot_path.with_suffix(".db.sha256").read_text(encoding="ascii").strip() != _file_checksum(snapshot_path):
            raise RuntimeError("Snapshot checksum mismatch")
        database_module = sys.modules.get("backend.db.session")
        if database_module is not None:
            database_module.engine.dispose()
        with closing(sqlite3.connect(_readonly_uri(snapshot_path), uri=True, timeout=10)) as source:
            _verify_sqlite(source)
            with closing(sqlite3.connect(db_path, timeout=10)) as destination:
                _sqlite_backup(source, destination)
                _verify_sqlite(destination)
        logger.info("Database restored from snapshot: %s", snapshot_name)
        return True
    except Exception:
        logger.exception("Failed to restore database snapshot")
        return False


# ─── Restart Signal ──────────────────────────────────────────────────────────

def signal_restart() -> dict:
    """Report manual restart instructions; there is no marker-file supervisor."""
    return {
        "restart_signaled": False,
        "restart_required": True,
        "manual_restart_required": True,
        "message": (
            "Ein automatischer Neustart ist nicht eingerichtet. Bitte die Anwendung stoppen "
            "und mit start.bat bzw. python -m backend erneut starten."
        ),
    }
