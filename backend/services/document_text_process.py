"""Run every document parser/OCR step inside the existing owned process limits."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from .document_text_reader import Budget, ExtractionPart
from .runtime_process import frozen_cli_executable

TEXT_TIMEOUT_SECONDS = 30
TEXT_WORK_BYTES = 128 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024


def worker_command(folder: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [frozen_cli_executable(), "document-text-worker", str(folder)]
    return [frozen_cli_executable(), "-m", "backend.services.document_text_worker", str(folder)]


def read_isolated(content: bytes, name: str, cursor: dict, budget: Budget) -> ExtractionPart:
    from .e_invoice.validator import _protect_windows_directory, _run

    if not content:
        return ExtractionPart()
    if len(content) > budget.file_bytes:
        return ExtractionPart(warning="Die Datei überschreitet das Lesebudget; der Inhalt ist nicht indiziert.")
    try:
        with tempfile.TemporaryDirectory(prefix="immo-e-invoice-text-") as directory:
            folder = Path(directory)
            if os.name == "nt":
                _protect_windows_directory(folder)
            (folder / "source.bin").write_bytes(content)
            request = {"name": str(name)[-200:], "cursor": cursor, "limits": asdict(budget)}
            raw = json.dumps(request, ensure_ascii=False).encode("utf8")
            if len(raw) > 16 * 1024:
                raise ValueError("Text cursor too large")
            (folder / "input.json").write_bytes(raw)
            env = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "TESSDATA_PREFIX"}}
            env.update(
                DOCUMENT_TEXT_READ_DIR=str(folder),
                PYTHONPATH=str(Path(__file__).resolve().parents[2]),
                PYTHONUTF8="1",
                DATA_DIR=str(folder),
                DATABASE_URL="sqlite:///:memory:",
                SECRET_KEY_FILE=str(folder / "keyring.json"),
                INTEGRATION_STATE_FILE=str(folder / "integrations.json"),
                JOB_SCHEDULER_ENABLED="false",
                BACKUP_SCHEDULE_ENABLED="false",
                ENVIRONMENT="development",
            )
            executable = shutil.which("tesseract")
            if executable:
                env["IMMO_TEXT_TESSERACT"] = executable
            if "TESSDATA_PREFIX" not in env:
                models = Path(__file__).resolve().parents[1] / "resources/tessdata"
                if all((models / (language + ".traineddata")).is_file() for language in ["deu", "eng"]):
                    env["TESSDATA_PREFIX"] = str(models)
            code, _, _ = _run(
                worker_command(folder),
                folder,
                environment=env,
                timeout_seconds=TEXT_TIMEOUT_SECONDS,
                max_processes=4,
                file_limit_bytes=TEXT_WORK_BYTES,
                resource_mode="text",
            )
            result = folder / "result.json"
            if code or not result.is_file() or result.stat().st_size > MAX_JSON:
                raise ValueError("Text worker did not complete")
            value = json.loads(result.read_text(encoding="utf8"))
            part = ExtractionPart(**value)
            if (
                not isinstance(part.text, str)
                or len(part.text) > budget.characters + 2
                or type(part.complete) is not bool
                or not isinstance(part.cursor, dict)
                or part.source not in {"none", "plain", "office", "pdf_text", "ocr"}
                or type(part.indexed_units) is not int
                or type(part.total_units) is not int
                or part.indexed_units < 0
                or part.total_units < part.indexed_units
                or (part.warning is not None and (not isinstance(part.warning, str) or len(part.warning) > 2000))
            ):
                raise ValueError("Invalid text worker response")
            return part
    except Exception:
        return ExtractionPart(
            warning="Die isolierte Dokumentauswertung wurde wegen eines Lese- oder Ressourcenlimits nicht vollständig beendet. Suchtreffer können fehlen; bitte das begrenzte Dokument prüfen oder erneut lesen."
        )
