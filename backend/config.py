"""Centralized configuration using pydantic-settings.

All environment variables are consolidated here. Import `settings` to use them.
"""

import enum
import importlib.metadata
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_version() -> str:
    """Read version from package metadata, falling back to pyproject.toml."""
    try:
        return importlib.metadata.version("immomanager-pro")
    except importlib.metadata.PackageNotFoundError:
        pass
    # Fallback: parse pyproject.toml directly
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text().splitlines():
            if line.strip().startswith("version"):
                return line.split("=")[1].strip().strip('"').strip("'")
    return "0.0.0"


class Environment(str, enum.Enum):
    """Recognised deployment environments."""
    development = "development"
    staging = "staging"
    production = "production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment profile ---
    # Set to "production" to enable strict safety checks at startup.
    environment: Environment = Environment.development

    # --- Application ---
    app_version: str = _get_version()
    app_title: str = "ImmoManager Pro API"

    # --- Database ---
    database_url: str = "sqlite:///./immo_manager.db"

    # --- Authentication ---
    # In production, this MUST be overridden — startup will fail if left at the
    # default value when ENVIRONMENT=production.
    jwt_secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- CORS ---
    # In production, explicit origins are required (no wildcards).
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # --- Logging ---
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"
    log_file: str | None = None

    # --- i18n ---
    default_locale: str = "de-DE"

    # --- Plugins ---
    plugin_dirs: list[str] = []

    # --- Auto-migration ---
    auto_migrate: bool = False

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

    # --- File upload limits ---
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB

    # --- Updates ---
    # GitHub repository URL for checking updates (e.g. "https://github.com/owner/repo")
    update_repo_url: str = ""
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

    # --- Contract wizard runtime behavior ---
    contract_wizard_required: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.production


settings = Settings()
