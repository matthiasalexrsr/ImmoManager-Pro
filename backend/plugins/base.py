"""Abstract base class for ImmoManager Pro plugins."""

from abc import ABC, abstractmethod
from pathlib import Path

from fastapi import FastAPI


class Plugin(ABC):
    """Base class all plugins must inherit from.

    Plugins provide routes, migrations, locales, and lifecycle hooks.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (lowercase, no spaces)."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string (e.g. '1.0.0')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description."""
        return ""

    @abstractmethod
    def register_routes(self, app: FastAPI, prefix: str) -> None:
        """Register FastAPI routes under the given prefix.

        Example: app.include_router(self.router, prefix=prefix)
        """
        ...

    def on_startup(self) -> None:
        """Called when the application starts."""
        pass

    def on_shutdown(self) -> None:
        """Called when the application shuts down."""
        pass

    def get_migrations_dir(self) -> Path | None:
        """Return path to Alembic migrations directory, or None."""
        return None

    def get_locale_dir(self) -> Path | None:
        """Return path to i18n locale files directory, or None."""
        return None

    def to_dict(self) -> dict:
        """Serialize plugin metadata for API responses."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
        }
