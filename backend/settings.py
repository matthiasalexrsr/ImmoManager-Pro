"""Centralized configuration using pydantic-settings.

All environment variables are consolidated here. Import `settings` to use them.
"""

import enum
import importlib.metadata
import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Independent field-encryption keys; never generated from JWT secrets.
    encryption_key: str = ""
    encryption_keyring: str = ""
    encryption_active_key_id: str = "default"
    encryption_index_key: str = ""
    encryption_legacy_jwt_keys: str = "[]"

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
    ]
    # Private server deployments provide their exact VPN/LAN hostname.
    trusted_hosts: Annotated[list[str], NoDecode] = ["*"]

    # --- Logging ---
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"
    log_file: str | None = None

    # --- i18n ---
    default_locale: str = "de-DE"

    # --- Plugins ---
    plugin_dirs: Annotated[list[str], NoDecode] = []

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

    # Operational batch sizes bound work per tick, never total stored records.
    operational_scheduler_enabled: bool = False
    operational_scheduler_actor_id: str | None = None
    operational_scheduler_interval_seconds: int = Field(default=300, ge=10, le=86400)
    operational_scheduler_max_items: int = Field(default=500, ge=1)
    operational_scheduler_lookback_days: int = Field(default=366, ge=1)
    booking_page_max_size: int = Field(default=500, ge=25, le=5000)
    workflow_reference_page_budget: int = Field(default=1000, ge=1)
    workflow_reference_cursor_seconds: int = Field(default=3600, ge=1)
    rent_batch_max_size: int = Field(default=500, ge=25, le=5000)
    bank_import_page_max_size: int = Field(default=500, ge=25, le=5000)
    bank_import_field_max_chars: int = Field(default=100000, ge=1024, le=100000000)
    # Discovery refuses a resource overflow; these are not total row limits.
    bank_discovery_record_max_chars: int = Field(default=8 * 1024 * 1024, gt=0)
    bank_discovery_field_max_chars: int = Field(default=1024 * 1024, gt=0)
    bank_discovery_temp_max_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0)
    bank_discovery_timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    contract_workspace_page_max_size: int = Field(default=500, gt=0)
    contract_correspondence_page_max_size: int = Field(default=100, gt=0)
    tenancy_workflow_page_max_size: int = Field(default=500, gt=0)
    contract_workspace_search_max_chars: int = Field(default=200, gt=0)
    form_draft_ttl_days: int = Field(default=7, ge=1, le=365)
    form_draft_max_bytes: int = Field(default=262144, ge=1024, le=16777216)

    # --- File upload / bounded local OCR ---
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    ocr_languages: str = "deu+eng"
    ocr_pdfinfo_path: str = ""
    ocr_pdftotext_path: str = ""
    ocr_pdftoppm_path: str = ""
    ocr_tesseract_path: str = ""
    ocr_tessdata_path: str = ""
    ocr_render_dpi: int = Field(default=200, ge=1)
    ocr_max_pdf_pages: int = Field(default=80, ge=1)
    ocr_max_page_pixels: int = Field(default=20_000_000, ge=1)
    ocr_max_total_pixels: int = Field(default=120_000_000, ge=1)
    ocr_max_ram_bytes: int = Field(default=256 * 1024 * 1024, ge=1)
    ocr_max_temp_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    ocr_max_text_bytes: int = Field(default=4 * 1024 * 1024, ge=1)
    ocr_timeout_seconds: float = Field(default=90, gt=0, allow_inf_nan=False)

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
    integration_state_payload_bytes: int = Field(default=1024 * 1024, gt=0)
    integration_state_json_depth: int = Field(default=64, gt=0)
    integration_state_lock_timeout_seconds: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    # Work budgets per artifact/proof/response, never a total history count cap.
    integration_history_artifact_bytes: int = Field(default=16 * 1024 * 1024, gt=0)
    integration_history_page_bytes: int = Field(default=32 * 1024 * 1024, gt=0)
    integration_history_temp_bytes: int = Field(default=512 * 1024 * 1024, gt=0)
    integration_history_timeout_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)

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

    @field_validator("integration_state_payload_bytes", "integration_state_json_depth",
                     "integration_state_lock_timeout_seconds", mode="before")
    @classmethod
    def validate_integration_state_budget_type(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool):
            raise ValueError("Integration state budget must be numeric, not boolean")
        if info.field_name != "integration_state_lock_timeout_seconds":
            if isinstance(value, str):
                raw = value.strip()
                if not raw.isascii() or not raw.isdecimal():
                    raise ValueError("Integration state integer budget must be a positive integer")
            elif type(value) is not int:
                raise ValueError("Integration state integer budget must be a positive integer")
        return value

    @field_validator("integration_history_artifact_bytes", "integration_history_page_bytes",
                     "integration_history_temp_bytes", "integration_history_timeout_seconds", mode="before")
    @classmethod
    def validate_history_budget_type(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool):
            raise ValueError("Integration history budget must be numeric, not boolean")
        if info.field_name != "integration_history_timeout_seconds":
            if isinstance(value, str):
                raw = value.strip()
                if not raw.isascii() or not raw.isdecimal():
                    raise ValueError("Integration history byte budget must be an integer")
            elif type(value) is not int:
                raise ValueError("Integration history byte budget must be an integer")
        return value

    @field_validator("bank_discovery_record_max_chars", "bank_discovery_field_max_chars",
                     "bank_discovery_temp_max_bytes", "bank_discovery_timeout_seconds", mode="before")
    @classmethod
    def validate_bank_discovery_numeric_type(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool):
            raise ValueError("Bank discovery budget must be numeric, not boolean")
        if info.field_name != "bank_discovery_timeout_seconds" and not isinstance(value, str) and type(value) is not int:
            raise ValueError("Bank discovery byte/character budget must be an integer")
        return value

    @field_validator("ocr_languages")
    @classmethod
    def validate_ocr_languages(cls, value: str) -> str:
        from .ocr_configuration import validate_ocr_environment

        validate_ocr_environment({"OCR_LANGUAGES": value})
        return value

    @field_validator("ocr_render_dpi", "ocr_max_pdf_pages", "ocr_max_page_pixels", "ocr_max_total_pixels",
                     "ocr_max_ram_bytes", "ocr_max_temp_bytes", "ocr_max_text_bytes",
                     "ocr_timeout_seconds", mode="before")
    @classmethod
    def validate_ocr_numeric_type(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool):
            raise ValueError("OCR budget must be numeric, not boolean")
        if info.field_name != "ocr_timeout_seconds":
            if isinstance(value, str):
                from .ocr_configuration import validate_ocr_environment
                validate_ocr_environment({str(info.field_name).upper(): value})
            elif type(value) is not int:
                raise ValueError("OCR resource budget must be an integer")
        return value

    @field_validator("cors_origins", "cors_methods", "cors_headers", "trusted_hosts", "plugin_dirs", mode="before")
    @classmethod
    def parse_string_list_settings(cls, value: object) -> list[str]:
        return _parse_string_list(value)

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.production


class ExplicitSettings(Settings):
    """Validate a selected offline installation without process or CWD settings."""

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                  dotenv_settings, file_secret_settings):
        return (init_settings,)
