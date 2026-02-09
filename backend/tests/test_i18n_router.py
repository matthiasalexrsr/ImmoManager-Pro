from pathlib import Path

from backend.routers import i18n


def test_manifest_exists_and_has_default_locale() -> None:
    manifest = i18n.get_manifest()

    assert manifest["defaultLocale"] == "de-DE"
    assert any(locale["code"] == "de-DE" for locale in manifest["locales"])


def test_locale_file_matches_manifest() -> None:
    manifest = i18n.get_manifest()
    locale_entry = manifest["locales"][0]
    locale_data = i18n.get_locale(locale_entry["code"])

    assert locale_data["brand"]["productName"] == "ImmoManager Pro"


def test_i18n_dir_is_repo_root() -> None:
    path = i18n._i18n_dir()

    assert (path / "manifest.json").exists()
    assert (path / "de-DE.json").exists()
    assert "i18n" in path.parts
