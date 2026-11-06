"""An explicitly selected, persistent presentation workspace, isolated from live data.

This module deliberately imports no application settings or database objects:
the desktop and CLI must select these paths before either is imported.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import weakref
from pathlib import Path
from uuid import UUID

MARKER = "immomanager-demo-bw.json"
SCHEMA = "immomanager-demo-bw/1"
USERNAME = "demo.bw"
PASSWORD = "Immo-Demo-BW-2026!"
DATABASE = "demo-bw.sqlite3"
_guard_installed = False


def enabled() -> bool:
    return os.environ.get("IMMO_DEMO", "").strip().lower() in {"1", "true", "yes", "ja"}


def default_directory() -> Path:
    from backend.platform_paths import default_user_data_dir

    ordinary = default_user_data_dir()
    return ordinary.with_name("ImmoManagerProDemoBW")


def _read_marker(directory: Path) -> dict:
    file = directory / MARKER
    if file.is_symlink():
        raise RuntimeError("Der Demoordner darf nicht umgeleitet werden.")
    try:
        marker = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("Dieser Datenordner gehört nicht zum Demobestand.") from error
    if (not isinstance(marker, dict) or marker.get("schema") != SCHEMA
            or marker.get("database") != DATABASE or not isinstance(marker.get("identity"), str)):
        raise RuntimeError("Der Datenordner hat keine gültige Demo-Kennung.")
    return marker


def configure_environment(data_dir: str | Path | None = None) -> Path:
    """Select a new empty or already marked demo directory; never adopt live data."""
    directory = Path(data_dir).expanduser() if data_dir else default_directory()
    if directory.is_symlink():
        raise RuntimeError("Der Demoordner darf keine Verknüpfung sein.")
    directory = directory.resolve()
    from backend.platform_paths import default_user_data_dir

    if directory in {default_user_data_dir().resolve(), default_user_data_dir(testversion=True).resolve()}:
        raise RuntimeError("Der Demobestand benötigt einen getrennten Datenordner.")
    if directory.exists() and not (directory / MARKER).exists():
        if any(directory.iterdir()):
            raise RuntimeError("Ein vorhandener Datenbestand wird nicht als Demo verwendet. Bitte einen neuen Demoordner wählen.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not (directory / MARKER).exists():
        marker = {"schema": SCHEMA, "database": DATABASE, "identity": secrets.token_hex(24), "state": "new"}
        with (directory / MARKER).open("x", encoding="utf-8") as stream:
            json.dump(marker, stream)
    marker = _read_marker(directory)
    for name in (DATABASE, "demo-auth.key", "integrations.json", "logs", "uploads", "backups", "secrets"):
        managed = directory / name
        if managed.is_symlink() or (managed.is_file() and managed.stat().st_nlink != 1):
            raise RuntimeError("Demo-Dateien dürfen nicht mit einem anderen Bestand verbunden sein.")
    if not (directory / "demo-auth.key").exists():
        handle = os.open(directory / "demo-auth.key", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(handle, "w", encoding="ascii") as stream:
            stream.write(secrets.token_urlsafe(48))
    key = (directory / "demo-auth.key").read_text(encoding="ascii")
    # Existing provider credentials and deployment paths must never enter this
    # workspace, even when the same installed program manages live portfolios.
    prefixes = ("SMTP_", "IMAP_", "S3_", "AWS_", "AZURE_", "FINTS_", "BANKING_", "TEHA_", "AKTENWERK_",
                "OPENAI_", "ANTHROPIC_", "PORTAL_", "WEBHOOK_", "HUGGINGFACE_", "CODEX_", "CLAUDE_")
    for name in tuple(os.environ):
        if name.upper().startswith(prefixes) or name.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GITHUB_TOKEN", "GH_TOKEN", "SECRET_KEYS"}:
            os.environ.pop(name, None)
    values = {
        "IMMO_DEMO": "true", "IMMO_TESTVERSION": "false", "ENVIRONMENT": "production",
        "DATA_DIR": str(directory), "DATABASE_URL": "sqlite:///" + (directory / DATABASE).as_posix(),
        "UPLOADS_DIR": str(directory / "uploads"), "BACKUP_DIR": str(directory / "backups"),
        "LOG_FILE": str(directory / "logs/immomanager.log"), "JWT_SECRET_KEY": key,
        "SECRET_KEY_FILE": str(directory / "secrets/keyring.json"),
        "INTEGRATION_STATE_FILE": str(directory / "integrations.json"),
        "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false", "AUTO_SEED_DEMO_DATA": "false",
        "JOB_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULE_ENABLED": "false", "PLUGIN_DIRS": "[]",
        "FILE_STORAGE_BACKEND": "local", "PORTAL_ENABLED": "false", "PORTAL_LOCAL_TEST_MODE": "false",
        "UPDATE_ALLOW_IN_PRODUCTION": "false", "DIAGNOSTICS_ALLOW_IN_PRODUCTION": "false",
        "CORS_ORIGINS": "http://127.0.0.1:8766,http://localhost:8766", "DEVELOPER_TOOLS_ENABLED": "false",
    }
    os.environ.update(values)
    for child in ("uploads", "backups", "logs", "secrets"):
        path = directory / child
        if path.is_symlink():
            raise RuntimeError("Demo-Unterordner dürfen nicht umgeleitet werden.")
        path.mkdir(mode=0o700, exist_ok=True)
    # Identity is checked at every seed entry; an arbitrary IMMO_DEMO flag does
    # not authorize writing into an ordinary database.
    if not marker["identity"]:
        raise RuntimeError("Ungültige Demo-Kennung.")
    return directory


def validate_environment() -> Path:
    if not enabled():
        raise RuntimeError("Der Demomodus wurde nicht ausdrücklich gestartet.")
    directory = Path(os.environ.get("DATA_DIR", "")).resolve()
    _read_marker(directory)
    expected = "sqlite:///" + (directory / DATABASE).as_posix()
    if os.environ.get("DATABASE_URL") != expected or (directory / DATABASE).is_symlink():
        raise RuntimeError("Die Demo-Datenbank muss im eigenen Demoordner liegen.")
    return directory


class DemoOutboundBlocked(RuntimeError):
    pass


def install_backend_guards() -> None:
    """Only the demo backend calls this; desktop/Qt browser processes do not."""
    global _guard_installed
    validate_environment()
    if _guard_installed:
        return
    listeners: weakref.WeakSet[socket.socket] = weakref.WeakSet()

    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
            # Windows asyncio/socketpair may connect two sockets of this same
            # process. Only an actually owned loopback listener is eligible.
            if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
                for listener in tuple(listeners):
                    try:
                        if listener.fileno() >= 0 and listener.getsockname()[:2] == address[:2]:
                            return
                    except OSError:
                        continue
            raise DemoOutboundBlocked("In diesem Demobestand erfolgt keine externe Verbindung.")
        if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            host = args[0] if args else None
            if host not in {None, "", "localhost", "127.0.0.1", "::1"}:
                raise DemoOutboundBlocked("In diesem Demobestand erfolgt keine externe Namensauflösung.")
        if event == "socket.bind":
            address = args[1]
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
                raise DemoOutboundBlocked("Der Demobestand ist nur auf diesem Computer erreichbar.")
            if args[0].family in {socket.AF_INET, socket.AF_INET6}:
                listeners.add(args[0])
        # Managed local PDF/Office/Java validators and backup utilities remain
        # usable. Provider actions are stopped at the API boundary; Python
        # services and first-party Python workers share this network barrier.

    sys.addaudithook(audit)
    _guard_installed = True


def _defer_assistant_run(method: str, path: str) -> bool:
    """Only these authenticated endpoints verify the stored provider themselves."""
    parts = path.split("/")
    if method != "POST" or len(parts) != 7 or parts[:4] != ["", "api", "v1", "assistant"]:
        return False
    if (parts[4], parts[6]) not in {("conversations", "runs"), ("runs", "retry"), ("runs", "cancel")}:
        return False
    try:
        return str(UUID(parts[5])) == parts[5]
    except ValueError:
        return False


def blocked_action(method: str, path: str) -> bool:
    """Local editing/calculation is real; operations that can leave the workspace stop here."""
    if path.startswith(("/api/v1/updates", "/api/v1/diagnostics", "/api/v1/plugins")):
        return True
    if method in {"GET", "HEAD", "OPTIONS"}:
        return False
    if path.startswith(("/api/v1/banking", "/api/v1/fints", "/api/v1/portal", "/api/v1/external-portal")):
        return True
    if path.startswith("/api/v1/integrations/") and path.endswith("/run"):
        return True
    if path.startswith("/api/v1/assistant/") and any(part in path for part in ("/login", "/probe", "/runs", "/apply")):
        # This only delegates provider decisions. submit/retry/cancel check
        # the authenticated owner, current source rights and encrypted stored
        # conversation provider before even returning an idempotent replay.
        return not _defer_assistant_run(method, path)
    if path.startswith("/api/v1/communication/") and any(part in path for part in ("/receive", "/confirm", "/retry", "/reconcile")):
        return True
    return any(part in path for part in ("/send", "/publish", "/sync", "/webhook", "/restore", "/restart"))


def seed_demo(app=None) -> bool:
    """Seed exactly once. Existing presentation edits and credentials are preserved."""
    directory = validate_environment()
    marker = _read_marker(directory)
    if marker.get("state") == "complete":
        return False
    if marker.get("state") != "new":
        raise RuntimeError("Die erste Einrichtung des Demobestands wurde unterbrochen. Der vorhandene Bestand bleibt erhalten; bitte einen neuen Demoordner wählen.")
    from backend import auth
    from backend.dependencies import store

    if store.list_portfolios() or auth.get_user_by_username(USERNAME):
        raise RuntimeError("Ein vorhandener Datenbestand wird nicht automatisch mit Demodaten ergänzt.")
    marker["state"] = "building"
    (directory / MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
    try:
        from .dataset import seed_dataset

        owner = auth.register_user(USERNAME, "demo.bw@verwaltung.invalid", "Nora Seidel", PASSWORD, "eigentuemer")
        summary = seed_dataset(store, directory, owner_id=owner.id)
        from backend.dependencies import cleanup_session
        cleanup_session()
    except Exception:
        marker["state"] = "failed"
        (directory / MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
        raise
    marker.update(state="complete", summary=summary)
    (directory / MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return True


def health_fields() -> dict:
    if not enabled():
        return {"demo": False}
    directory = validate_environment()
    marker = _read_marker(directory)
    return {"demo": True, "demo_region": "Baden-Württemberg", "demo_ready": marker.get("state") == "complete",
            "demo_login": {"username": USERNAME, "password": PASSWORD}}
