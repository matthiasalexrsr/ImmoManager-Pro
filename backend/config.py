"""Application settings loaded once from its environment and runtime .env."""

from .settings import Environment, Settings

__all__ = ["Environment", "Settings", "settings"]

settings = Settings()
