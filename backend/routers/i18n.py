import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/i18n", tags=["i18n"])


def _i18n_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "i18n"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Locale nicht gefunden") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Locale ungültig") from exc


@router.get("/manifest")
def get_manifest() -> dict:
    return _load_json(_i18n_dir() / "manifest.json")


@router.get("/{locale}")
def get_locale(locale: str) -> dict:
    return _load_json(_i18n_dir() / f"{locale}.json")
