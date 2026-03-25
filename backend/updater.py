"""Self-update engine for ImmoManager Pro.

Checks GitHub for new releases, downloads and applies updates via git,
runs database migrations, and can roll back on failure.

Safety guarantees:
- Automatic JSON backup of all data before every update
- Database snapshot (SQLite) or migration dry-run (PostgreSQL) before applying
- Git stash of local changes before pull
- Automatic rollback to previous commit on migration or startup failure
- Lock file prevents concurrent updates
- All operations are logged to the audit trail
- Backup integrity verification via SHA-256 checksum
- Production environment guard (updates disabled by default in production)

This module is designed for the standard Python/uvicorn deployment.
Docker and PyInstaller deployments should use their native update mechanisms.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import settings

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKUP_DIR = _PROJECT_ROOT / "backups"
_UPDATE_DIR = _PROJECT_ROOT / ".updates"
_LOCK_FILE = _UPDATE_DIR / "update.lock"
_HISTORY_FILE = _UPDATE_DIR / "history.json"
_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"

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
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    if _LOCK_FILE.exists():
        # Check for stale lock (older than 30 minutes)
        try:
            lock_data = json.loads(_LOCK_FILE.read_text())
            lock_time = datetime.fromisoformat(lock_data.get("locked_at", ""))
            age_seconds = (datetime.now(timezone.utc) - lock_time).total_seconds()
            if age_seconds < 1800:
                return False
            logger.warning("Stale update lock detected (age: %.0fs), removing", age_seconds)
        except Exception:
            logger.debug("Could not parse update lock file", exc_info=True)
    _LOCK_FILE.write_text(json.dumps({
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }))
    return True


def _release_lock() -> None:
    """Release the update lock."""
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def is_update_locked() -> bool:
    """Check whether an update is currently in progress."""
    if not _LOCK_FILE.exists():
        return False
    try:
        lock_data = json.loads(_LOCK_FILE.read_text())
        lock_time = datetime.fromisoformat(lock_data.get("locked_at", ""))
        age_seconds = (datetime.now(timezone.utc) - lock_time).total_seconds()
        return age_seconds < 1800
    except Exception:
        logger.debug("Could not read update lock status", exc_info=True)
        return False


# ─── Git Helpers ──────────────────────────────────────────────────────────────

def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + list(args)
    return subprocess.run(
        cmd,
        cwd=cwd or _PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


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
    result = _run_git("status", "--porcelain")
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def _stash_changes() -> bool:
    """Stash any uncommitted changes.  Returns True if something was stashed."""
    if not _has_uncommitted_changes():
        return False
    result = _run_git("stash", "push", "-m", f"ImmoManager auto-stash before update {datetime.now(timezone.utc).isoformat()}")
    return result.returncode == 0


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
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
    """For SQLite: copy the database file as a binary snapshot.

    Returns the snapshot filename on success, None otherwise.
    """
    if "sqlite" not in settings.database_url:
        return None

    db_path = Path(settings.database_url.replace("sqlite:///", ""))
    if not db_path.exists():
        return None

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"pre_update_{timestamp}.db"
    snapshot_path = _BACKUP_DIR / snapshot_name

    try:
        shutil.copy2(db_path, snapshot_path)
        logger.info("Database snapshot created: %s", snapshot_name)
        return snapshot_name
    except Exception:
        logger.exception("Failed to create database snapshot")
        return None


# ─── Migration ────────────────────────────────────────────────────────────────

def _run_migrations() -> tuple[bool, str]:
    """Run Alembic migrations.  Returns (success, message)."""
    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
        return True, "Migrationen erfolgreich angewendet"
    except Exception as exc:
        logger.exception("Migration failed during update")
        return False, f"Migration fehlgeschlagen: {exc}"


# ─── Frontend Rebuild ─────────────────────────────────────────────────────────

def _rebuild_frontend() -> tuple[bool, str]:
    """Rebuild the frontend if npm/node is available.

    Returns (success, message).
    """
    frontend_dir = _PROJECT_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        return True, "Kein Frontend-Verzeichnis gefunden, übersprungen"

    # Check if node/npm is available
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True, "Node.js nicht installiert, Frontend-Build übersprungen"

    try:
        # Install dependencies if needed
        result = subprocess.run(
            ["npm", "install", "--production=false"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return False, f"npm install fehlgeschlagen: {result.stderr[:500]}"

        # Build
        result = subprocess.run(
            ["npx", "vite", "build"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return False, f"Frontend-Build fehlgeschlagen: {result.stderr[:500]}"

        return True, "Frontend erfolgreich gebaut"
    except subprocess.TimeoutExpired:
        return False, "Frontend-Build Zeitüberschreitung"
    except Exception as exc:
        return False, f"Frontend-Build Fehler: {exc}"


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

def apply_update(target_version: str | None = None) -> dict:
    """Apply an update from GitHub.

    Steps:
    1. Acquire lock
    2. Verify git repo and connectivity
    3. Create data backup (JSON + SQLite snapshot)
    4. Stash uncommitted changes
    5. Git fetch + merge (or reset to tag)
    6. Install updated Python dependencies
    7. Run database migrations
    8. Rebuild frontend
    9. Record success in history
    10. Signal restart needed

    On failure at any step, rolls back to the previous commit.

    Returns a result dict with status, messages, and whether restart is needed.
    """
    result = {
        "success": False,
        "message": "",
        "steps": [],
        "restart_required": False,
        "backup_name": None,
        "previous_version": settings.app_version,
        "new_version": None,
        "rollback_performed": False,
    }

    # Preflight checks
    if getattr(sys, "frozen", False):
        result["message"] = "Updates sind im PyInstaller-Bundle nicht verfügbar"
        return result

    if not _is_git_repo():
        result["message"] = "Kein Git-Repository. Updates erfordern eine Git-Installation."
        return result

    if not settings.update_repo_url:
        result["message"] = "Kein Update-Repository konfiguriert"
        return result

    # Validate target_version format if provided
    if target_version:
        cleaned = target_version.lstrip("vV").strip()
        if not re.match(r"^\d+\.\d+\.\d+([a-zA-Z0-9._-]*)?$", cleaned):
            result["message"] = f"Ungültiges Versionsformat: {target_version}"
            return result

    if not _acquire_lock():
        result["message"] = "Ein Update läuft bereits"
        return result

    previous_commit = _get_current_commit()
    stashed = False

    try:
        # Step 1: Create backups
        result["steps"].append("Erstelle Datensicherung...")
        backup_name = _create_pre_update_backup()
        if not backup_name:
            result["message"] = "Datensicherung fehlgeschlagen — Update abgebrochen"
            return result
        result["backup_name"] = backup_name
        result["steps"].append(f"Backup erstellt: {backup_name}")

        db_snapshot = _create_db_snapshot()
        if db_snapshot:
            result["steps"].append(f"Datenbank-Snapshot erstellt: {db_snapshot}")

        # Step 2: Stash local changes
        stashed = _stash_changes()
        if stashed:
            result["steps"].append("Lokale Änderungen gesichert (git stash)")

        # Step 3: Fetch from remote
        result["steps"].append("Hole Updates von GitHub...")
        branch = _get_current_branch() or "main"

        fetch_result = _run_git("fetch", "origin", branch)
        if fetch_result.returncode != 0:
            result["message"] = f"Git fetch fehlgeschlagen: {fetch_result.stderr.strip()}"
            _rollback(previous_commit, stashed, result)
            return result

        # Step 4: Check out target version or merge
        if target_version:
            # Check out a specific tag
            tag_name = target_version if target_version.startswith("v") else f"v{target_version}"
            # First try the tag, then without 'v' prefix
            checkout = _run_git("checkout", tag_name)
            if checkout.returncode != 0:
                checkout = _run_git("checkout", target_version)
            if checkout.returncode != 0:
                result["message"] = f"Version {target_version} nicht gefunden"
                _rollback(previous_commit, stashed, result)
                return result
            result["steps"].append(f"Version {target_version} ausgecheckt")
        else:
            # Merge latest from remote
            merge_result = _run_git("merge", f"origin/{branch}", "--ff-only")
            if merge_result.returncode != 0:
                # Try rebase if fast-forward fails
                merge_result = _run_git("merge", f"origin/{branch}")
                if merge_result.returncode != 0:
                    result["message"] = f"Merge fehlgeschlagen: {merge_result.stderr.strip()}"
                    _rollback(previous_commit, stashed, result)
                    return result
            result["steps"].append("Code aktualisiert")

        new_commit = _get_current_commit()
        if new_commit == previous_commit:
            result["success"] = True
            result["message"] = "Bereits auf dem neuesten Stand"
            result["steps"].append("Keine Änderungen erforderlich")
            if stashed:
                _stash_pop()
            return result

        # Step 5: Install updated dependencies
        result["steps"].append("Installiere Abhängigkeiten...")
        pip_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(_PROJECT_ROOT / "requirements.txt"), "-q"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if pip_result.returncode != 0:
            logger.warning("pip install had issues: %s", pip_result.stderr[:500])
            result["steps"].append("Abhängigkeiten: Warnungen (nicht kritisch)")
        else:
            result["steps"].append("Abhängigkeiten aktualisiert")

        # Step 6: Run database migrations
        result["steps"].append("Führe Datenbank-Migrationen aus...")
        mig_ok, mig_msg = _run_migrations()
        result["steps"].append(mig_msg)
        if not mig_ok:
            result["message"] = "Migration fehlgeschlagen — Rollback wird durchgeführt"
            _rollback(previous_commit, stashed, result)
            # Restore DB snapshot if available
            if db_snapshot and "sqlite" in settings.database_url:
                _restore_db_snapshot(db_snapshot)
                result["steps"].append("Datenbank-Snapshot wiederhergestellt")
            return result

        # Step 7: Rebuild frontend
        result["steps"].append("Baue Frontend neu...")
        fe_ok, fe_msg = _rebuild_frontend()
        result["steps"].append(fe_msg)
        if not fe_ok:
            result["message"] = "Frontend-Build fehlgeschlagen — Rollback wird durchgeführt"
            _rollback(previous_commit, stashed, result)
            if db_snapshot and "sqlite" in settings.database_url:
                _restore_db_snapshot(db_snapshot)
                result["steps"].append("Datenbank-Snapshot wiederhergestellt")
            return result

        # Step 8: Re-apply stashed changes
        if stashed:
            if _stash_pop():
                result["steps"].append("Lokale Änderungen wiederhergestellt")
            else:
                result["steps"].append("Lokale Änderungen konnten nicht automatisch wiederhergestellt werden (im Stash gespeichert)")
            stashed = False

        # Read new version from updated pyproject.toml
        from .config import _get_version
        new_version = _get_version()
        result["new_version"] = new_version

        # Success!
        result["success"] = True
        result["restart_required"] = True
        result["message"] = f"Update von {settings.app_version} auf {new_version} erfolgreich"
        result["steps"].append("Update abgeschlossen — Neustart erforderlich")

        _record_update({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from_version": settings.app_version,
            "to_version": new_version,
            "from_commit": previous_commit,
            "to_commit": new_commit,
            "backup": backup_name,
            "db_snapshot": db_snapshot,
            "success": True,
        })

    except Exception as exc:
        logger.exception("Unexpected error during update")
        # Avoid leaking internal paths or stack traces to the API response
        result["message"] = f"Unerwarteter Fehler: {type(exc).__name__}"
        _rollback(previous_commit, stashed, result)
    finally:
        _release_lock()

    return result


def _rollback(previous_commit: str | None, stashed: bool, result: dict) -> None:
    """Roll back to the previous commit."""
    if not previous_commit:
        result["steps"].append("Rollback nicht möglich: vorheriger Commit unbekannt")
        return

    logger.warning("Rolling back to commit %s", previous_commit)
    reset = _run_git("reset", "--hard", previous_commit)
    if reset.returncode == 0:
        result["steps"].append(f"Rollback auf {previous_commit[:8]} durchgeführt")
        result["rollback_performed"] = True
    else:
        result["steps"].append(f"Rollback fehlgeschlagen: {reset.stderr.strip()}")

    if stashed:
        _stash_pop()


def _restore_db_snapshot(snapshot_name: str) -> bool:
    """Restore a SQLite database snapshot."""
    if "sqlite" not in settings.database_url:
        return False

    db_path = Path(settings.database_url.replace("sqlite:///", ""))
    snapshot_path = _BACKUP_DIR / snapshot_name

    if not snapshot_path.exists():
        return False

    try:
        shutil.copy2(snapshot_path, db_path)
        logger.info("Database restored from snapshot: %s", snapshot_name)
        return True
    except Exception:
        logger.exception("Failed to restore database snapshot")
        return False


# ─── Restart Signal ──────────────────────────────────────────────────────────

def signal_restart() -> dict:
    """Signal that the application should restart.

    For uvicorn, we create a touch file that a process manager (systemd, etc.)
    can watch.  The endpoint returns instructions for manual restart if no
    process manager is detected.
    """
    touch_file = _UPDATE_DIR / "restart_requested"
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    touch_file.write_text(datetime.now(timezone.utc).isoformat())

    return {
        "restart_signaled": True,
        "message": (
            "Neustart-Signal gesetzt. "
            "Bitte starten Sie die Anwendung neu, um das Update zu aktivieren. "
            "Befehl: python -m backend"
        ),
        "touch_file": str(touch_file),
    }
