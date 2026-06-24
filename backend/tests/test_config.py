"""Tests for environment-driven application settings."""

from backend.config import Settings


def test_settings_accepts_csv_list_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    monkeypatch.setenv("PLUGIN_DIRS", "plugins/core, plugins/custom")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:5173"]
    assert settings.plugin_dirs == ["plugins/core", "plugins/custom"]


def test_settings_accepts_json_list_environment(monkeypatch):
    monkeypatch.setenv("CORS_METHODS", '["GET", "POST", "OPTIONS"]')
    monkeypatch.setenv("CORS_HEADERS", '["Authorization", "Content-Type"]')

    settings = Settings(_env_file=None)

    assert settings.cors_methods == ["GET", "POST", "OPTIONS"]
    assert settings.cors_headers == ["Authorization", "Content-Type"]
