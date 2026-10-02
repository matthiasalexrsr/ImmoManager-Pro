"""Actual private configuration/recovery hooks; no global settings or user data."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from backend.ocr_configuration import OCR_DEFAULTS, OCR_INTEGER_BUDGETS, OCR_PATH_KEYS
from backend.settings import ExplicitSettings
from backend.tests.test_full_recovery import plan, runtime_template  # noqa: F401 — shared synthetic fixtures
from scripts import private_server_backup

ROOT = Path(__file__).resolve().parents[2]
SERVER = ("APP_ORIGIN=https://example.test\nAPP_HOST=example.test\nAPP_HTTP_PORT=8080\n"
          "POSTGRES_USER=immo\nPOSTGRES_DB=immomanager\nPOSTGRES_PASSWORD=" + "a" * 64 +
          "\nJWT_SECRET_KEY=" + "b" * 96 + "\n")


def test_settings_private_backup_and_compose_cover_every_ocr_key():
    values = ExplicitSettings().model_dump()
    for key, default in OCR_DEFAULTS.items():
        assert str(values[key.lower()]) == default or key == "OCR_TIMEOUT_SECONDS" and values[key.lower()] == float(default)
    parsed = private_server_backup._parse_env((SERVER + "".join(f"{key}={value}\n" for key, value in OCR_DEFAULTS.items())).encode())
    assert {key: parsed[key] for key in OCR_DEFAULTS} == OCR_DEFAULTS
    compose = (ROOT / "compose.private-server.yml").read_text(encoding="utf-8")
    for key in OCR_DEFAULTS:
        assert key + ":" in compose
    from backend.services.full_recovery import _configuration
    assert _configuration({**OCR_DEFAULTS, "JWT_SECRET_KEY": "synthetic-recovery-config"})["OCR_TESSDATA_PATH"] == ""


@pytest.mark.parametrize("key,value", [("OCR_LANGUAGES", "deu++eng"), ("OCR_RENDER_DPI", "0"),
    ("OCR_TIMEOUT_SECONDS", "NaN"), ("OCR_MAX_RAM_BYTES", "0"), ("OCR_TESSDATA_PATH", "/unsafe/$path")])
def test_private_backup_rejects_invalid_ocr_values_without_exposing_data(key, value):
    with pytest.raises(private_server_backup.BackupError) as error:
        private_server_backup._parse_env((SERVER + f"{key}={value}\n").encode())
    assert value not in str(error.value)


def test_optional_empty_paths_do_not_allow_empty_language_or_other_configuration():
    for key in OCR_PATH_KEYS:
        assert private_server_backup._parse_env((SERVER + f"{key}=\n").encode())[key] == ""
    for key in ("OCR_LANGUAGES", "OCR_TIMEOUT_SECONDS", "FORM_DRAFT_TTL_DAYS"):
        with pytest.raises(private_server_backup.BackupError):
            private_server_backup._parse_env((SERVER + f"{key}=\n").encode())


def test_explicit_large_budgets_are_preserved_by_settings_and_private_backup_without_ceilings():
    from backend.services.full_recovery import _configuration

    configured = {
        "OCR_RENDER_DPI": "1200",
        "OCR_MAX_PDF_PAGES": "100000", "OCR_MAX_PAGE_PIXELS": "1000000000",
        "OCR_MAX_TOTAL_PIXELS": "6000000000", "OCR_MAX_RAM_BYTES": "17179869184",
        "OCR_MAX_TEMP_BYTES": "34359738368", "OCR_MAX_TEXT_BYTES": "536870912",
        "OCR_TIMEOUT_SECONDS": "86400.5",
    }
    settings = ExplicitSettings(**{key.lower(): value for key, value in configured.items()})
    for key in OCR_INTEGER_BUDGETS:
        assert getattr(settings, key.lower()) == int(configured[key])
    assert settings.ocr_timeout_seconds == 86400.5
    parsed = private_server_backup._parse_env((SERVER + "".join(f"{key}={value}\n" for key, value in configured.items())).encode())
    assert {key: parsed[key] for key in configured} == configured
    recovery = _configuration({**configured, "JWT_SECRET_KEY": "synthetic-budget-config"})
    assert {key: float(recovery[key]) for key in configured} == {key: float(value) for key, value in configured.items()}


@pytest.mark.parametrize("key", sorted(OCR_INTEGER_BUDGETS))
@pytest.mark.parametrize("value", ["0", "-1", "0.5", "1.0", "true", "NaN", "inf"])
def test_integer_budgets_reject_nonpositive_or_fractional_settings_and_private_backup(key, value):
    with pytest.raises(ValueError):
        ExplicitSettings(**{key.lower(): value})
    with pytest.raises(private_server_backup.BackupError):
        private_server_backup._parse_env((SERVER + f"{key}={value}\n").encode())


def test_boolean_budget_is_not_coerced_to_one_in_application_configuration():
    for key in OCR_INTEGER_BUDGETS | {"OCR_TIMEOUT_SECONDS"}:
        with pytest.raises(ValueError):
            ExplicitSettings(**{key.lower(): True})


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "inf", "-inf"])
def test_timeout_is_positive_and_finite_in_both_configuration_paths(value):
    with pytest.raises(ValueError):
        ExplicitSettings(ocr_timeout_seconds=value)
    with pytest.raises(private_server_backup.BackupError):
        private_server_backup._parse_env((SERVER + f"OCR_TIMEOUT_SECONDS={value}\n").encode())


@pytest.mark.parametrize("field,value", [("max_pdf_pages", 0), ("max_temp_bytes", 1.5),
    ("max_ram_bytes", True), ("timeout_seconds", float("inf")), ("timeout_seconds", float("nan"))])
def test_explicit_operation_budgets_fail_closed_before_any_tool(field, value, monkeypatch):
    from backend.services import ocr_service

    def unexpected_tool(*args):
        raise AssertionError("Invalid operation budgets must fail before tool lookup")
    monkeypatch.setattr(ocr_service, "_resolve_tool", unexpected_tool)
    with pytest.raises(ocr_service.OCRProcessingError) as error:
        ocr_service.extract_pdf_text_local(b"%PDF-1.7\n", limits=replace(ocr_service.OCRLimits(), **{field: value}))
    assert error.value.code == "ocr_config_invalid" and error.value.http_status == 503


def test_ram_setting_is_unbounded_but_windows_size_t_is_never_silently_truncated():
    from backend.services import ocr_service

    too_large_for_native = 1 << (8 * ctypes.sizeof(ctypes.c_size_t))
    assert ExplicitSettings(ocr_max_ram_bytes=too_large_for_native).ocr_max_ram_bytes == too_large_for_native
    limits = ocr_service.OCRLimits(max_ram_bytes=too_large_for_native)
    if os.name == "nt":
        with pytest.raises(ocr_service.OCRProcessingError) as error:
            ocr_service._validate_limits(limits)
        assert error.value.code == "ocr_config_invalid" and "Windows" in error.value.message
    else:
        ocr_service._validate_limits(limits)  # Linux samples Python's exact integer budget.


def test_actual_frozen_desktop_runtime_persists_ocr_overrides_before_config_import_and_restart(tmp_path):
    environment = {key: value for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT"}}
    environment.update(PYTHONPATH=str(ROOT), PYTHONUTF8="1", LOCALAPPDATA=str(tmp_path / "private"),
        OCR_TESSDATA_PATH=str(tmp_path / "local tools" / "tessdata"), OCR_TIMEOUT_SECONDS="37", OCR_LANGUAGES="eng")
    child = r'''
import json, sys
from pathlib import Path
from backend import __main__ as launcher
from backend.ocr_configuration import OCR_DEFAULTS
assert 'backend.config' not in sys.modules
launcher.IS_FROZEN = True
launcher._exe_dir = lambda: sys.argv[1]
root = Path(launcher._configure_runtime_environment())
assert 'backend.config' not in sys.modules
from backend.settings import Settings
settings = Settings()
assert settings.ocr_timeout_seconds == 37 and settings.ocr_languages == 'eng'
saved = (root/'.env').read_text(encoding='utf-8')
for key in OCR_DEFAULTS:
    assert key+'=' in saved
assert 'OCR_TESSDATA_PATH='+settings.ocr_tessdata_path in saved
print(json.dumps({'root':str(root),'tessdata':settings.ocr_tessdata_path}))
'''
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    result = subprocess.run([sys.executable, "-c", child, str(bundle)], cwd=tmp_path, env=environment,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    first = json.loads(result.stdout)
    for key in OCR_DEFAULTS:
        environment.pop(key, None)
    second = subprocess.run([sys.executable, "-c", child, str(bundle)], cwd=tmp_path, env=environment,
                            capture_output=True, timeout=30)
    assert second.returncode == 0, second.stderr.decode("utf-8", errors="replace")
    assert json.loads(second.stdout) == first


def test_complete_sourcegone_recovery_retains_selected_ocr_settings(plan, tmp_path):  # noqa: F811 — imported fixture
    from backend.services import full_recovery as recovery
    configured = {**OCR_DEFAULTS, "OCR_TESSDATA_PATH": str(tmp_path / "separate-native-tools" / "tessdata"),
                  "OCR_TIMEOUT_SECONDS": "37.5", "OCR_MAX_PDF_PAGES": "23"}
    values = {**plan.configuration, **configured}
    selected = recovery.RecoveryPlan(plan.database, plan.uploads, values, plan.runtime_env, plan.integration_state)
    archive = tmp_path / "ocr-complete.immobak"
    recovery.create_full_backup(selected, archive, "Synthetic OCR complete recovery", offline=True)
    source = selected.database.parent.resolve()
    assert source.is_relative_to(tmp_path.resolve()) and source.name == "source"
    shutil.rmtree(source)
    destination = tmp_path / "recovered"
    recovery.restore_full_backup(archive, destination, "Synthetic OCR complete recovery")
    restored = json.loads((destination / "configuration.json").read_text(encoding="utf-8"))
    assert {key: restored[key] for key in configured} == configured
    environment = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1", "OCR_TESSDATA_PATH": "foreign-path",
                   "OCR_TIMEOUT_SECONDS": "invalid-ambient-value"}
    script = "from pathlib import Path;import sys;from backend.services.full_recovery import load_recovered_environment;load_recovered_environment(Path(sys.argv[1]));from backend.config import settings;assert settings.ocr_timeout_seconds==37.5;assert settings.ocr_max_pdf_pages==23;assert settings.ocr_tessdata_path==sys.argv[2];print('OCR_RECOVERY_OK')"
    result = subprocess.run([sys.executable, "-c", script, str(destination), configured["OCR_TESSDATA_PATH"]],
                            cwd=tmp_path, env=environment, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert b"OCR_RECOVERY_OK" in result.stdout
