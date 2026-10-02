"""Validated, account-scoped display preferences with truthful persistence."""
import logging
from threading import RLock
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update

logger = logging.getLogger(__name__)


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    theme: Literal["light", "dark", "system"] = "light"
    locale: Literal["de-DE", "en-US", "es-ES"] = "de-DE"
    sidebar_collapsed: bool = False
    items_per_page: Literal[10, 25, 50, 100] = 25
    date_format: Literal["DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"] = "DD.MM.YYYY"
    currency: Literal["EUR", "CHF", "USD"] = "EUR"
    default_due_day: int = Field(default=1, ge=1, le=28)
    email_notifications: Literal["all", "important", "none"] = "important"
    reminder_days: Literal["3", "7", "14", "30"] = "7"


DEFAULTS = PreferencesInput().model_dump()
_memory: dict[str, dict] = {}
_lock = RLock()


def read_preferences(user_id: str, session) -> dict:
    if session is None:
        with _lock:
            return {**DEFAULTS, **_memory.get(user_id, {})}
    try:
        from ..db.orm_models import UserPreferencesORM
        row = session.query(UserPreferencesORM).filter(UserPreferencesORM.user_id == user_id).first()
        return {key: getattr(row, key) for key in DEFAULTS} if row else dict(DEFAULTS)
    except Exception:
        logger.warning("Could not load account display preferences")
        raise HTTPException(503, "Anzeigeeinstellungen konnten nicht geladen werden.") from None
    finally:
        session.close()


def write_preferences(user_id: str, payload: PreferencesInput, session) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if session is None:
        with _lock:
            value = {**DEFAULTS, **_memory.get(user_id, {}), **changes}
            _memory[user_id] = value
            return dict(value)
    try:
        from ..db.orm_models import UserORM, UserPreferencesORM
        # Lock the existing parent before reading the optional preference row.
        # SQLite obtains its write lock here; PostgreSQL locks this user's row.
        result = session.execute(update(UserORM).where(UserORM.id == user_id).values(id=UserORM.id))
        if result.rowcount != 1:
            raise HTTPException(401, "Benutzerkonto ist nicht mehr verfügbar.")
        row = session.query(UserPreferencesORM).filter(UserPreferencesORM.user_id == user_id).first()
        if row is None:
            row = UserPreferencesORM(user_id=user_id, **{**DEFAULTS, **changes})
            session.add(row)
        else:
            for key, value in changes.items():
                setattr(row, key, value)
        session.commit()
        return {key: getattr(row, key) for key in DEFAULTS}
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        logger.warning("Could not save account display preferences")
        raise HTTPException(503, "Anzeigeeinstellungen konnten nicht gespeichert werden.") from None
    finally:
        session.close()
