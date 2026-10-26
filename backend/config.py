"""Centralized configuration using pydantic-settings.

All environment variables are consolidated here. Import `settings` to use them.
"""

import enum
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SETTING_ORIGINS: dict[str, str] = {}
SETTING_ORIGIN_FILES: dict[str, str] = {}


def _packaged_invoice_bundle() -> str:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    candidate = root / ("e-invoice" if getattr(sys, "frozen", False) else "artifacts/e-invoice")
    return str(candidate) if candidate.is_dir() else ""


def _get_version(pyproject: Path | None = None) -> str:
    """The version of the running code: pyproject.toml next to it, else the package metadata.

    A checkout (also an editable install) and the Windows package carry pyproject.toml. The metadata
    of an editable install keeps the version of its installation: after an update it would still name
    the old version, and the update check would offer the installed update again.
    """
    import tomllib

    pyproject = pyproject or Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        version = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    except (OSError, ValueError):
        pass
    try:
        return importlib.metadata.version("immomanager-pro")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


class Environment(str, enum.Enum):
    """Recognised deployment environments."""
    development = "development"
    staging = "staging"
    production = "production"


def _parse_string_list(value: object) -> list[str]:
    """Accept JSON arrays and comma-separated strings for list settings."""
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return [str(value).strip()]

    raw = value.strip()
    if not raw:
        return []

    if raw.startswith("["):
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("expected a JSON array")
        return [str(item).strip() for item in parsed if str(item).strip()]

    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(os.environ["DATA_DIR"]) / ".env")) if os.environ.get("DATA_DIR") else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        def tracked(source, origin):
            def read():
                values = source()
                for name in values:
                    if name not in SETTING_ORIGINS:
                        SETTING_ORIGINS[name] = origin
                        if origin == "dotenv_file":
                            from dotenv import dotenv_values
                            files = source.env_file
                            files = [files] if isinstance(files, (str, Path)) else files or []
                            for path in files:
                                if name.lower() in {key.lower() for key in dotenv_values(path)}:
                                    SETTING_ORIGIN_FILES[name] = str(Path(path).resolve())
                return values
            return read
        return tuple(tracked(source, origin) for source, origin in (
            (init_settings, "explicit"), (env_settings, "process_env"),
            (dotenv_settings, "dotenv_file"), (file_secret_settings, "secret_file")))

    # --- Environment profile ---
    # Set to "production" to enable strict safety checks at startup.
    environment: Environment = Environment.development

    # --- Application ---
    app_version: str = _get_version()
    app_title: str = "ImmoManager Pro API"
    portal_enabled: bool = False
    portal_public_url: str = ""
    portal_local_test_mode: bool = False

    # --- Database ---
    database_url: str = "sqlite:///./immo_manager.db"

    # --- Runtime data paths ---
    # Leave empty for source/Docker defaults. Windows launchers and frozen
    # bundles set these to a persistent per-user data directory.
    data_dir: str = ""
    uploads_dir: str = ""
    backup_dir: str = ""

    # --- Authentication ---
    # In production, this MUST be overridden — startup will fail if left at the
    # default value when ENVIRONMENT=production.
    jwt_secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- CORS ---
    # In production, explicit origins are required (no wildcards).
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    cors_methods: Annotated[list[str], NoDecode] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    cors_headers: Annotated[list[str], NoDecode] = [
        "Authorization",
        "Content-Type",
        "Accept",
        "Accept-Language",
        "X-Request-ID",
        "X-Token-Transport",
    ]

    # --- Browser security headers (backend/middleware.py SecurityHeadersMiddleware) ---
    security_headers_enabled: bool = True
    # replaces the built-in Content-Security-Policy, e.g. for files served from another origin
    content_security_policy: str = ""
    # Strict-Transport-Security over HTTPS; 0 switches it off (e.g. while testing a new certificate)
    hsts_max_age: int = 31536000
    # API documentation (/docs, /redoc, /openapi.json); unset: on, except with ENVIRONMENT=production
    api_docs_enabled: bool | None = None

    @property
    def api_docs(self) -> bool:
        return self.api_docs_enabled if self.api_docs_enabled is not None else self.environment != Environment.production

    # --- Logging ---
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"
    log_file: str | None = None

    # --- i18n ---
    default_locale: str = "de-DE"

    # --- Plugins ---
    plugin_dirs: Annotated[list[str], NoDecode] = []
    immo_restore_probe: bool = False

    file_storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "immomanager"
    s3_region: str = "eu-central-1"

    # --- Scheduled jobs ---
    # Every process ticks; durable runs and leases keep one worker per job.
    job_scheduler_enabled: bool = True
    # Explicit, hash-verified local bundle; no download or ambient Java at runtime.
    e_invoice_bundle: str = Field(default_factory=_packaged_invoice_bundle)
    e_invoice_timeout_seconds: int = Field(default=90, ge=5, le=180)
    job_scheduler_interval_seconds: float = 60.0
    # "latest": only the newest missed occurrence of a series becomes a task; "all": every one
    recurring_catch_up: Literal["latest", "all"] = "latest"

    # --- Auto-migration ---
    # Ignored since the explicit upgrade (python -m backend.upgrade); kept so old .env files load.
    auto_migrate: bool = False
    # A unique epoch is written by full restore, including manual PostgreSQL restores.
    # Search, AI and external portal access stay closed until the privacy review.
    privacy_restore_id: str = ""

    # --- Secrets at rest ---
    # Key file for integration secrets (default: <DATA_DIR>/secrets/keyring.json, created on first use).
    secret_key_file: str = ""
    # Alternative: comma-separated base64url 32-byte keys, the first one active (never written to disk).
    secret_keys: str = ""

    # Optional official account clients. Leave empty for discovery on this
    # server; no API key or operator-global credential directory is used.
    assistant_codex_cli: str = ""
    assistant_claude_cli: str = ""
    assistant_max_attachment_bytes: int | None = Field(default=None, gt=0)
    assistant_request_attachment_bytes: int = Field(default=128 * 1024 * 1024, gt=0)

    # --- Full backups and restore probes ---
    # Daily full backup and monthly restore probe as durable jobs (Europe/Berlin).
    backup_schedule_enabled: bool = True
    backup_daily_at: str = "01:30"
    restore_probe_day: int = 1
    restore_probe_at: str = "03:30"
    backup_keep_daily: int = 14
    backup_keep_monthly: int = 6
    backup_keep_pre_upgrade: int = 3
    # Second target (e.g. a network share); every copy is verified by SHA-256.
    backup_second_target: str = ""
    # Optional: protects the key file and .env inside the archive (scrypt + AES-256-GCM).
    backup_passphrase: str = ""
    # PostgreSQL: directory of pg_dump/pg_restore when not on PATH, and an optional admin URL of a
    # disposable server for full restore probes (a database is created and dropped there).
    pg_bin_dir: str = ""
    restore_probe_postgres_url: str = ""

    # --- Persistence toggles ---
    # SQLite uses SQLAlchemyStore by default for real data persistence.
    # Set to False only for tests that require in-memory repositories.
    sqlite_persistent_store: bool = True

    # When False (default), abort startup if the configured database cannot be
    # initialized.  Set to True only for development/demo environments.
    allow_inmemory_fallback: bool = False

    # --- Demo seeding ---
    # When True, seeds demo data on startup if the database is empty.
    # Defaults to False; must be explicitly enabled (e.g. for demo images).
    auto_seed_demo_data: bool = False

    # --- Test version ---
    # Package sent to testers: realistic data set (15 properties) and master logins on
    # the first start (backend.testversion); the UI shows a "Testversion" badge.
    immo_testversion: bool = False

    # --- Accounts ---
    # The very first account is always created as owner (initial setup).
    # Afterwards, public self-registration stays closed unless enabled here;
    # self-registered accounts are always read-only.
    allow_self_registration: bool = False

    # --- File upload limits ---
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB

    # --- Updates ---
    # GitHub repository whose releases the update check reads (only when someone clicks "Jetzt prüfen")
    update_repo_url: str = "https://github.com/matthiasalexrsr/ImmoManager-Pro"
    # "stable" = only released versions; "preview" = include pre-releases
    update_channel: str = "stable"
    # Optional GitHub personal access token for private repos / higher rate limits
    update_github_token: str = ""
    # Allow self-update in production (default False for safety)
    update_allow_in_production: bool = False

    # --- Diagnostics ---
    # Allow diagnostics endpoint in production (default False)
    diagnostics_allow_in_production: bool = False

    # --- Integrations ---
    integration_state_file: str | None = None
    # Per-command processing budget, not a cap on a connection or its history.
    integration_step_max_bytes: int = 4 * 1024 * 1024

    # --- AI / Hugging Face ---
    ai_enabled: bool = True  # Master toggle for AI features
    ai_device: str = "cpu"  # "cpu" or "cuda"
    ai_cache_dir: str = ""  # HF model cache directory (empty = default)
    ai_summarization_model: str = "facebook/bart-large-cnn"
    ai_zero_shot_model: str = "facebook/bart-large-mnli"
    ai_ner_model: str = "dslim/bert-base-NER"
    ai_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ai_max_input_length: int = 4096

    # --- Contract wizard runtime behavior ---
    contract_wizard_required: bool = False

    @field_validator("cors_origins", "cors_methods", "cors_headers", "plugin_dirs", mode="before")
    @classmethod
    def parse_string_list_settings(cls, value: object) -> list[str]:
        return _parse_string_list(value)

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.production

    @property
    def developer_tools_enabled(self) -> bool:
        """Diagnostics, autotest and dev notes: on outside production,
        in production only with DIAGNOSTICS_ALLOW_IN_PRODUCTION=true."""
        return not self.is_production or self.diagnostics_allow_in_production


MIN_JWT_SECRET_LENGTH = 32

settings = Settings()
