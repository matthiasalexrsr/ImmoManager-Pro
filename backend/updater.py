"""Customer release discovery and a separate explicit developer deployment CLI.

Customers install a verified package with the application stopped. HTTP never
promotes source code. The optional non-production developer CLI requires a clean
checkout, exact HTTPS origin, named version tag and immutable expected commit.
It supports local SQLite only, with a full backup, verified rollback snapshot
and durable write fences. Interrupted or incomplete recovery never expires by
age and requires operator verification before the source installation is used.
Git identity/hash binding is not publisher-signature verification.
"""

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .config import settings
from .paths import get_backup_dir, get_data_dir
from .services.filesystem_paths import filesystem_path
from .services.runtime_process import frozen_cli_executable

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKUP_DIR = filesystem_path(get_backup_dir())
_UPDATE_DIR = filesystem_path(get_data_dir()) / ".updates"
_LOCK_FILE = _UPDATE_DIR / "update.lock"
_HISTORY_FILE = _UPDATE_DIR / "history.json"
_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"

# Timeout for GitHub API requests
_HTTP_TIMEOUT = 30.0
INSTALLER_HINT = (
    "ImmoManager Pro schließen und das geprüfte Installationspaket der neuen Version verwenden. "
    "Bei portablen Paketen in einen neuen Ordner entpacken. Der bestehende Datenordner bleibt erhalten; "
    "vor einer nötigen Datenbankmigration wird zuerst ein geprüftes Vollbackup angelegt. "
    "Die laufende Anwendung ersetzt ihren Quellcode nicht selbst."
)
_lock_mutex = threading.Lock()
_owned_lock_token: str | None = None
_retain_lock = False


# ─── Version Comparison ──────────────────────────────────────────────────────

_VERSION = re.compile(r"(\d+(?:\.\d+)*)(?:[-.]?([a-zA-Z]+)[-.]?(\d*))?")
# a pre-release comes before its release: 2.0.0-dev < -alpha < -beta.1 < -beta.2 < -rc1 < 2.0.0
_PHASES = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "c": 3, "rc": 3, "pre": 3, "preview": 3}
_RELEASED = 4


def _parse_version(version_str: str) -> tuple[tuple[int, ...], int, int]:
    """'1.2.3', 'v2.1.0-rc1', '2.0.0-beta.2' or '2.0.0b2' as a comparable key; '+build' does not count."""
    if not isinstance(version_str, str) or len(version_str) > 80 or not re.fullmatch(
            r"[vV]?[^+\s]+(?:\+[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", version_str):
        return ((), 0, 0)
    cleaned = version_str.removeprefix("v").removeprefix("V").split("+")[0]
    match = _VERSION.fullmatch(cleaned)
    if not match:
        return ((), 0, 0)
    numbers = [int(number) for number in match.group(1).split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:      # 2.0 is 2.0.0
        numbers.pop()
    phase = match.group(2)
    if phase is None:
        return (tuple(numbers), _RELEASED, 0)
    if phase.lower() not in _PHASES:
        return ((), 0, 0)
    return (tuple(numbers), _PHASES.get(phase.lower(), 0), int(match.group(3) or 0))


def is_newer_version(remote: str, local: str) -> bool:
    """Return True if `remote` is strictly newer than `local`."""
    remote_key, local_key = _parse_version(remote), _parse_version(local)
    return bool(remote_key[0] and local_key[0]) and remote_key > local_key


# ─── Lock Management ─────────────────────────────────────────────────────────

def _acquire_lock() -> bool:
    """Exclusive creation; an interrupted or unreadable lock never expires by age."""
    global _owned_lock_token, _retain_lock
    with _lock_mutex:
        if _owned_lock_token is not None:
            return False
        _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(_LOCK_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            return False
        token = secrets.token_hex(24)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"locked_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
                           "token": token}, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            # Keep a partially written marker: removing it could reopen writes
            # after an uncertain filesystem failure.
            raise
        _owned_lock_token, _retain_lock = token, False
        return True


def _release_lock() -> None:
    """Only the acquiring invocation may remove its own unchanged marker."""
    global _owned_lock_token
    with _lock_mutex:
        token = _owned_lock_token
        _owned_lock_token = None
        if token is None or _retain_lock:
            return
        try:
            info = _LOCK_FILE.lstat()
            value = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
            if stat.S_ISREG(info.st_mode) and value.get("token") == token and value.get("pid") == os.getpid():
                _LOCK_FILE.unlink()
        except (OSError, ValueError, AttributeError):
            logger.warning("Update lock could not be released safely", exc_info=True)


def is_update_locked() -> bool:
    """A leftover marker requires recovery, including after a process crash."""
    try:
        _LOCK_FILE.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _transaction_state() -> dict:
    try:
        value = json.loads((_UPDATE_DIR / "transaction.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("phase") not in {
            "prepared", "applying", "installed", "rolled_back", "recovery_required"
        }:
            raise ValueError("Invalid update transaction")
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {"phase": "recovery_required"}


def _save_transaction(value: dict) -> None:
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _UPDATE_DIR / (".transaction-" + secrets.token_hex(8) + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _UPDATE_DIR / "transaction.json")
    finally:
        temporary.unlink(missing_ok=True)


# Set once an update is installed: this process still runs the previous code on the new schema.
_restart_pending = False


def writes_blocked() -> str | None:
    """Why changes are refused right now, or None.

    During an update a failed step restores the database snapshot taken at its start, which
    would drop whatever was saved in between; after it, the old code would write into the
    new schema until the restart.
    """
    if _restart_pending:
        return "Das Update ist installiert. Bitte ImmoManager neu starten; bis dahin sind Änderungen gesperrt."
    state = _transaction_state()
    if state.get("phase") == "installed":
        if state.get("new_version") != settings.app_version:
            return "Das Update ist installiert. Bitte ImmoManager neu starten; bis dahin sind Änderungen gesperrt."
    elif state.get("phase") in {"prepared", "applying", "recovery_required"}:
        return "Ein Quellcode-Update ist nicht vollständig abgeschlossen. Änderungen bleiben bis zur geprüften Wiederherstellung gesperrt."
    if is_update_locked():
        return "Ein Update läuft. Änderungen sind bis zu seinem Ende gesperrt; Lesen geht weiter."
    return None


# ─── Git Helpers ──────────────────────────────────────────────────────────────

def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git", "--no-replace-objects", "-c", "core.fsmonitor=false",
           "-c", "core.hooksPath=" + str(_UPDATE_DIR / "disabled-hooks"), *args]
    return subprocess.run(
        cmd,
        cwd=cwd or _PROJECT_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _is_git_repo() -> bool:
    """Check whether the project root is a git repository."""
    try:
        result = _run_git("rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _get_current_commit() -> str | None:
    """Return the current HEAD commit hash."""
    result = _run_git("rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _get_current_branch() -> str | None:
    """Return the current git branch name."""
    result = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _source_mismatch() -> str | None:
    """Why the checkout cannot install what the update check reports, if it pulls from another repository.

    The check reads the releases of UPDATE_REPO_URL; apply_update fetches from the checkout's origin.
    """
    configured = _extract_owner_repo(settings.update_repo_url or "")
    remote = _run_git("remote", "get-url", "origin")
    origin = remote.stdout.strip() if remote.returncode == 0 else ""
    if not configured:
        return "Die Updatequelle ist keine exakte HTTPS-GitHub-Repositoryadresse."
    if origin and (_extract_owner_repo(origin) or "").lower() == configured.lower():
        return None
    if not origin:
        return "Der Checkout hat kein Remote „origin“; ein Update lässt sich nicht holen."
    # never show credentials of an https remote
    shown = _extract_owner_repo(origin) or "einer ungültigen oder nicht zugelassenen Remoteadresse"
    return (f"Die Update-Prüfung liest {configured}, der Checkout holt seinen Code aber von {shown}. "
            "Bitte UPDATE_REPO_URL oder das Remote „origin“ angleichen.")


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
        "is_git_repo": False if getattr(sys, "frozen", False) else _is_git_repo(),
        "update_channel": channel,
        "is_frozen": getattr(sys, "frozen", False),
        # Customer updates always use the verified installer, including source checkouts.
        "can_apply": False,
        "download_hint": None,
        "update_method": "verified_installer",
    }

    if not repo_url:
        result["error"] = "Kein GitHub-Repository konfiguriert (UPDATE_REPO_URL)"
        return result

    # Extract owner/repo from URL
    owner_repo = _extract_owner_repo(repo_url)
    if not owner_repo:
        result["error"] = "Die Updatequelle ist keine gültige HTTPS-GitHub-Repositoryadresse."
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
            if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
                raise ValueError("Keine gültige veröffentlichte Version")
            release = data
        else:
            # data is a list, newest first by date; the highest version wins (a fix of an older line
            # published after a pre-release does not hide it)
            if not isinstance(data, list):
                raise ValueError("Ungültige Release-Liste")
            published = [item for item in data if isinstance(item, dict) and not item.get("draft")
                         and _parse_version(str(item.get("tag_name", "")))[0]]
            if not published:
                result["error"] = "Keine Releases gefunden"
                return result
            release = max(published, key=lambda item: _parse_version(item.get("tag_name", "")))

        tag = release.get("tag_name", "")
        if not isinstance(tag, str) or not _parse_version(tag)[0]:
            raise ValueError("Ungültige Release-Version")
        if channel == "stable" and _parse_version(tag)[1] != _RELEASED:
            raise ValueError("Keine stabile veröffentlichte Version")
        result["latest_version"] = tag.lstrip("vV")
        body = release.get("body", "")
        result["release_notes"] = body[:128000] if isinstance(body, str) else ""
        # Never expose an arbitrary link supplied by release metadata.
        result["release_url"] = f"https://github.com/{owner_repo}/releases/tag/{quote(tag, safe='')}"
        published_at = release.get("published_at", "")
        result["published_at"] = published_at[:80] if isinstance(published_at, str) else ""
        result["update_available"] = is_newer_version(tag, current)
        if result["update_available"]:
            result["download_hint"] = INSTALLER_HINT

    except httpx.TimeoutException:
        result["error"] = "Zeitüberschreitung bei der Verbindung zu GitHub"
    except httpx.HTTPStatusError as exc:
        result["error"] = f"GitHub API Fehler: HTTP {exc.response.status_code}"
    except Exception:
        logger.exception("Update check failed")
        result["error"] = "Die Updateinformationen konnten nicht verlässlich geprüft werden."

    return result


def _extract_owner_repo(url: str) -> str | None:
    """An exact HTTPS GitHub identity, never a substring or credential URL."""
    if not isinstance(url, str) or len(url) > 500 or any(ord(c) < 33 for c in url):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc.lower() not in {"github.com", "github.com:443"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            return None
    except ValueError:
        return None
    match = re.fullmatch(r"/([A-Za-z0-9][A-Za-z0-9_-]{0,99})/([A-Za-z0-9][A-Za-z0-9._-]{0,99})/?", parsed.path)
    if not match:
        return None
    owner, repository = match.groups()
    repository = repository.removesuffix(".git")
    return f"{owner}/{repository}" if repository else None


# ─── Data Backup ──────────────────────────────────────────────────────────────

def _create_pre_update_backup() -> str | None:
    """Create a full data backup before updating.

    Returns the backup filename on success, None on failure.
    """
    try:
        from .services.full_backup import Sources, create_full_backup
        event = create_full_backup("pre-upgrade", Sources.from_settings())
        if not event.get("ok"):
            return None
        return event["archive"]
    except Exception:
        logger.exception("Failed to create pre-update backup")
        return None


def _create_db_snapshot() -> str | None:
    """For SQLite: copy the database file as a binary snapshot.

    Returns the snapshot filename on success, None otherwise.
    """
    from .services.sqlite_backup import sqlite_path_from_url
    db_path = sqlite_path_from_url(settings.database_url)
    if db_path is not None:
        db_path = filesystem_path(db_path)
    if db_path is None or str(db_path) == ":memory:" or not db_path.is_file():
        return None

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"pre_update_{timestamp}_{secrets.token_hex(8)}.db"
    snapshot_path = filesystem_path(_BACKUP_DIR / snapshot_name)

    try:
        # online backup API: a file copy of the live WAL database would miss commits
        from .services.full_backup import sqlite_online_copy
        fd = os.open(snapshot_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        sqlite_online_copy(db_path, snapshot_path)
        digest = hashlib.sha256()
        with snapshot_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        from .services.secret_box import write_private_file
        write_private_file(snapshot_path.with_suffix(".db.sha256"), digest.hexdigest().encode("ascii"))
        logger.info("Database snapshot created: %s", snapshot_name)
        return snapshot_name
    except Exception:
        logger.exception("Failed to create database snapshot")
        return None


# ─── Dependencies ────────────────────────────────────────────────────────────

def _install_dependencies() -> tuple[bool, str]:
    """The exact dependency tree of the checked-out code (requirements.txt with constraints.txt)."""
    command = [frozen_cli_executable(), "-m", "pip", "install", "-q", "-r", str(_PROJECT_ROOT / "requirements.txt")]
    constraints = _PROJECT_ROOT / "constraints.txt"
    if constraints.exists():
        command += ["-c", str(constraints)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=600,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        logger.exception("pip could not be started during update")
        return False, f"pip fehlgeschlagen: {type(exc).__name__}"
    if result.returncode != 0:
        logger.error("pip install failed during update: %s", result.stderr[-2000:])
        return False, f"pip fehlgeschlagen (Code {result.returncode}): {result.stderr.strip()[-500:]}"
    return True, "Abhängigkeiten aktualisiert"


# ─── Migration ────────────────────────────────────────────────────────────────

def _run_migrations() -> tuple[bool, str]:
    """Explicit upgrade with the updated code, in its own process (full backup first)."""
    try:
        result = subprocess.run([frozen_cli_executable(), "-m", "backend.upgrade"], cwd=str(_PROJECT_ROOT),
                                capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=6 * 3600,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        logger.exception("Upgrade could not be started during update")
        return False, f"Upgrade fehlgeschlagen: {type(exc).__name__}"
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        logger.error("Explicit upgrade failed during update: %s", output[-2000:])
        return False, f"Upgrade fehlgeschlagen (Code {result.returncode}): {output[-500:]}"
    return True, output.splitlines()[-1] if output else "Datenbank ist aktuell"


# ─── Frontend Rebuild ─────────────────────────────────────────────────────────

def _npm_command() -> list[str]:
    """Run npm's JavaScript entry directly on Windows, without a cmd window."""
    if sys.platform != "win32":
        return ["npm"]
    command = shutil.which("npm.cmd")
    if not command:
        raise FileNotFoundError("npm.cmd nicht gefunden")
    cli = Path(command).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not cli.is_file():
        raise FileNotFoundError("Der npm-Einstiegspunkt fehlt; Node.js bitte erneut installieren")
    return ["node", str(cli)]


def _rebuild_frontend() -> tuple[bool, str]:
    """Rebuild the frontend if npm/node is available.

    Returns (success, message).
    """
    frontend_dir = _PROJECT_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        return True, "Kein Frontend-Verzeichnis gefunden, übersprungen"

    # Check if node/npm is available
    try:
        subprocess.run(["node", "--version"], capture_output=True, stdin=subprocess.DEVNULL, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "Node.js fehlt; der erforderliche Frontend-Build wurde nicht ausgeführt"

    try:
        npm = _npm_command()
        # Exactly the locked packages, as CI and the release build use them; npm install
        # would rewrite package-lock.json and leave the checkout changed
        result = subprocess.run(
            [*npm, "ci", "--include=dev"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return False, f"npm ci fehlgeschlagen: {result.stderr[:500]}"

        # Build
        result = subprocess.run(
            [*npm, "run", "build"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
    """Read only a bounded list of history entries; corrupt optional history is ignored."""
    if not _HISTORY_FILE.exists():
        return []
    try:
        if _HISTORY_FILE.stat().st_size > 1024 * 1024:
            return []
        value = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        return value[-50:] if isinstance(value, list) and all(isinstance(entry, dict) for entry in value) else []
    except Exception:
        logger.debug("Could not load update history file", exc_info=True)
        return []


def _save_history(history: list[dict]) -> None:
    """Save the update history to disk."""
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    from .services.secret_box import write_private_file
    write_private_file(_HISTORY_FILE, json.dumps(history, ensure_ascii=False, indent=2).encode("utf-8"))


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

def apply_update(target_version: str | None = None, *, developer_mode: bool = False,
                 expected_commit: str | None = None) -> dict:
    """Offline developer deployment only; HTTP/customer promotion is disabled.

    A caller must deliberately name the exact tag and immutable commit. This is
    not installer publisher-signature verification and is not a customer update
    guarantee. A stopped application and a clean source checkout are required.
    """
    global _restart_pending
    result: dict[str, Any] = {
        "success": False, "message": "", "steps": [], "restart_required": False,
        "backup_name": None, "previous_version": settings.app_version,
        "new_version": None, "rollback_performed": False, "recovery_required": False,
    }
    if not developer_mode:
        result["message"] = INSTALLER_HINT
        return result
    if getattr(sys, "frozen", False) or settings.is_production:
        result["message"] = "Der Entwickler-Quellcodepfad ist für Paket- und Produktionsinstallationen gesperrt. " + INSTALLER_HINT
        return result
    from .services.sqlite_backup import sqlite_path_from_url
    database = sqlite_path_from_url(settings.database_url)
    if database is not None:
        database = filesystem_path(database)
    if database is None or str(database) == ":memory:" or not database.is_file():
        result["message"] = ("Automatische Quellcodeänderungen benötigen eine lokale SQLite-Datei. "
                             "Andere Datenbanken nur mit geprüftem Deployment, Vollbackup und ausdrücklichem Upgrade aktualisieren.")
        return result
    if (not isinstance(target_version, str) or len(target_version) > 80 or not re.fullmatch(
            r"[vV]?\d+\.\d+\.\d+(?:-(?:dev|alpha|beta|rc)\.\d+)?", target_version)
            or not isinstance(expected_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_commit)):
        result["message"] = "Exakter Versionstag und vollständiger erwarteter Commit sind für den Entwickleraufruf erforderlich."
        return result
    new_version = target_version.lstrip("vV")
    if not is_newer_version(new_version, settings.app_version):
        result["message"] = "Der Zielstand muss eine neuere Version sein; ein Downgrade wird nicht ausgeführt."
        return result
    state = _transaction_state()
    if state.get("phase") in {"prepared", "applying", "recovery_required"}:
        result["message"] = "Eine frühere Aktualisierung benötigt geprüfte Wiederherstellung; die Sperre wird nicht automatisch entfernt."
        return result
    if not _is_git_repo():
        result["message"] = "Kein Git-Quellcheckout für den Entwickleraufruf vorhanden."
        return result
    mismatch = _source_mismatch()
    if mismatch:
        result["message"] = mismatch
        return result
    if _has_uncommitted_changes():
        result["message"] = "Der Quellcheckout enthält lokale Änderungen. Diese zuerst bewusst sichern; sie werden nicht automatisch verworfen oder zusammengeführt."
        return result
    if not _acquire_lock():
        result["message"] = "Eine Aktualisierung läuft oder benötigt Wiederherstellung. Die Sperre wird nicht zeitgesteuert aufgehoben."
        return result
    previous_commit = None
    snapshot = None
    code_changed = dependencies_changed = frontend_changed = migration_attempted = False
    transaction: dict[str, Any] = {}
    try:
        previous_commit = _get_current_commit()
        if not previous_commit or not re.fullmatch(r"[0-9a-f]{40}", previous_commit):
            raise RuntimeError("Vorheriger Commit nicht eindeutig")
        result["steps"].append("Erstelle geprüftes Vollbackup und SQLite-Rückfallpunkt...")
        backup = _create_pre_update_backup()
        if not backup:
            raise RuntimeError("Vollbackup fehlgeschlagen")
        result["backup_name"] = backup
        snapshot = _create_db_snapshot()
        if not snapshot:
            raise RuntimeError("Pflichtsnapshot fehlgeschlagen; kein Code wird geändert")
        transaction = {"phase": "prepared", "at": datetime.now(timezone.utc).isoformat(),
                       "previous_commit": previous_commit, "expected_commit": expected_commit,
                       "previous_version": settings.app_version, "new_version": new_version,
                       "snapshot": snapshot, "backup": backup}
        _save_transaction(transaction)
        fetch = _run_git("fetch", "--no-tags", "origin", "refs/tags/" + target_version)
        if fetch.returncode:
            raise RuntimeError("Der exakte Zieltag konnte nicht geholt werden")
        fetched = _run_git("rev-parse", "--verify", "FETCH_HEAD^{commit}")
        if fetched.returncode or fetched.stdout.strip() != expected_commit:
            raise RuntimeError("Der geholte Tag entspricht nicht dem erwarteten Commit")
        if _run_git("merge-base", "--is-ancestor", previous_commit, expected_commit).returncode:
            raise RuntimeError("Der Zielcommit ist kein Fast-forward des geprüften Ausgangsstands")
        import tomllib
        project = _run_git("show", expected_commit + ":pyproject.toml")
        if project.returncode or tomllib.loads(project.stdout).get("project", {}).get("version") != new_version:
            raise RuntimeError("Versionstag und Version des Zielcommits stimmen nicht überein")
        transaction["phase"] = "applying"
        _save_transaction(transaction)
        code_changed = True
        changed = _run_git("merge", "--ff-only", expected_commit)
        if changed.returncode or _get_current_commit() != expected_commit:
            raise RuntimeError("Der exakte Zielstand konnte nicht vorspulend übernommen werden")
        dependencies_changed = True
        ok, message = _install_dependencies()
        result["steps"].append(message)
        if not ok:
            raise RuntimeError("Abhängigkeiten fehlgeschlagen")
        # Build before touching the schema. A missing tool is a failure, never a
        # successful skipped build serving old browser assets with a new API.
        frontend_changed = True
        ok, message = _rebuild_frontend()
        result["steps"].append(message)
        if not ok:
            raise RuntimeError("Frontend-Build fehlgeschlagen")
        migration_attempted = True
        ok, message = _run_migrations()
        result["steps"].append(message)
        if not ok:
            raise RuntimeError("Datenbank-Upgrade fehlgeschlagen")
        transaction["phase"] = "installed"
        _save_transaction(transaction)
        _restart_pending = True
        result.update(success=True, restart_required=True, new_version=new_version,
                      message=f"Entwicklerstand {new_version} exakt installiert; Anwendung neu starten.")
        # The durable installed checkpoint is the commit point. A secondary
        # history write may not revert code behind an already upgraded schema.
        try:
            _record_update({"timestamp": datetime.now(timezone.utc).isoformat(),
                            "from_version": settings.app_version, "to_version": new_version,
                            "from_commit": previous_commit, "to_commit": expected_commit,
                            "backup": backup, "db_snapshot": snapshot, "success": True})
        except Exception:
            logger.exception("Installed developer update history could not be saved")
            result["steps"].append("Updatehistorie nicht gespeichert; der dauerhafte Transaktionsnachweis und das Vollbackup bleiben maßgeblich.")
    except Exception as exc:
        logger.exception("Developer update failed")
        result.update(success=False, restart_required=False,
                      message=f"Entwickleraktualisierung abgebrochen: {type(exc).__name__}.")
        result["steps"].append(str(exc)[:300] if isinstance(exc, RuntimeError) else "Der geprüfte Ablauf konnte nicht abgeschlossen werden.")
        if previous_commit and code_changed:
            _rollback(previous_commit, False, result, dependencies_changed,
                      snapshot_name=snapshot if migration_attempted else None,
                      frontend_changed=frontend_changed)
        elif transaction:
            try:
                _save_transaction({**transaction, "phase": "rolled_back"})
            except Exception:
                _mark_recovery(result, transaction)
        elif previous_commit is None:
            _mark_recovery(result, transaction)
    finally:
        _release_lock()
    return result


def _mark_recovery(result: dict, transaction: dict | None = None) -> None:
    global _restart_pending, _retain_lock
    _restart_pending, _retain_lock = True, True
    result.update(success=False, recovery_required=True, restart_required=True, rollback_performed=False)
    try:
        _save_transaction({**(transaction or _transaction_state()), "phase": "recovery_required"})
    except Exception:
        logger.exception("Recovery state could not be saved; retaining the durable update lock")
    result["steps"].append("Wiederherstellung nicht vollständig bestätigt. Anwendung gestoppt lassen und Vollbackup sowie Quellstand prüfen; Änderungen bleiben gesperrt.")


def _rollback(previous_commit: str | None, stashed: bool, result: dict, dependencies_changed: bool = False,
              *, snapshot_name: str | None = None, frontend_changed: bool = False) -> None:
    """Only a complete code/dependency/assets/data recovery reopens writes."""
    del stashed  # dirty worktrees are refused before the first change
    complete = bool(previous_commit)
    try:
        reset = _run_git("reset", "--hard", previous_commit or "")
        complete = complete and reset.returncode == 0 and _get_current_commit() == previous_commit
    except Exception:
        logger.exception("Source rollback failed")
        complete = False
    if dependencies_changed:
        try:
            ok, message = _install_dependencies()
            result["steps"].append("Vorherige Abhängigkeiten: " + message)
            complete = complete and ok
        except Exception:
            logger.exception("Dependency rollback failed")
            complete = False
    if frontend_changed:
        try:
            ok, message = _rebuild_frontend()
            result["steps"].append("Vorheriges Frontend: " + message)
            complete = complete and ok
        except Exception:
            logger.exception("Frontend rollback failed")
            complete = False
    if snapshot_name:
        try:
            restored = _restore_db_snapshot(snapshot_name)
            result["steps"].append("Datenbank-Snapshot wiederhergestellt" if restored else "Datenbank-Snapshot nicht wiederhergestellt")
            complete = complete and restored
        except Exception:
            logger.exception("Database rollback failed")
            complete = False
    try:
        if complete:
            _save_transaction({**_transaction_state(), "phase": "rolled_back"})
            result["rollback_performed"] = True
        else:
            _mark_recovery(result)
    except Exception:
        logger.exception("Rollback checkpoint could not be saved")
        _mark_recovery(result)


def _restore_db_snapshot(snapshot_name: str) -> bool:
    from .services.sqlite_backup import copy_database, is_sqlite_database, sqlite_path_from_url
    database = sqlite_path_from_url(settings.database_url)
    if database is not None:
        database = filesystem_path(database)
    if database is None or Path(snapshot_name).name != snapshot_name:
        return False
    snapshot = filesystem_path(_BACKUP_DIR / snapshot_name)
    try:
        if snapshot.is_symlink() or not is_sqlite_database(snapshot):
            return False
        expected = snapshot.with_suffix(snapshot.suffix + ".sha256").read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            return False
        from .services.full_backup import sha256_file
        if sha256_file(snapshot) != expected:
            return False
        copy_database(snapshot, database)
        import sqlite3
        with sqlite3.connect(database) as connection:
            return connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    except Exception:
        logger.exception("Database snapshot restoration could not be verified")
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


def main(argv: list[str] | None = None) -> int:
    """Explicit source maintenance by the developer; never called by HTTP."""
    import argparse
    parser = argparse.ArgumentParser(description=(
        "Entwickler-Quellupdate für eine gestoppte lokale SQLite-Installation. "
        "Kein Kundeninstaller und keine Herausgebersignaturprüfung. "
        "Bei unterbrochener Transaktion Anwendung gestoppt lassen und Backup/Quellstand manuell prüfen."))
    parser.add_argument("--developer-mode", action="store_true", required=True)
    parser.add_argument("--target-version", required=True, help="Exakter Git-Versionstag, einschließlich vorhandenem v-Präfix")
    parser.add_argument("--expected-commit", required=True, help="Unabhängig geprüfter vollständiger 40-stelliger Commit")
    args = parser.parse_args(argv)
    from .desktop_control import acquire_instance_guard
    guard = acquire_instance_guard(get_data_dir())
    try:
        if guard.existed:
            print("Die Anwendung verwendet diesen Datenordner noch. Vor dem Entwicklerupdate vollständig schließen.")
            return 1
        result = apply_update(args.target_version, developer_mode=args.developer_mode,
                              expected_commit=args.expected_commit)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["success"] else 1
    finally:
        guard.close()


if __name__ == "__main__":
    raise SystemExit(main())
