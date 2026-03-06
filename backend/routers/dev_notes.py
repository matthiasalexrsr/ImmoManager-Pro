"""Developer Mode — annotation & improvement notes API.

Allows developers to pin notes to specific locations in the application.
Notes are persisted in-memory and also written to a structured log file
(``dev_notes.log``) that can be fed back to an AI assistant for targeted
improvements.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dev-notes", tags=["Developer Mode"])

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DevNoteCreate(BaseModel):
    page: str = Field(..., description="Route/page where the note was created, e.g. '/properties'")
    component: Optional[str] = Field(None, description="Component or section identifier")
    selector: Optional[str] = Field(None, description="CSS selector or element identifier for the annotated area")
    category: str = Field("improvement", description="Category: improvement | bug | idea | todo | question")
    priority: str = Field("medium", description="Priority: low | medium | high | critical")
    title: str = Field(..., min_length=1, description="Short summary of the note")
    description: Optional[str] = Field(None, description="Detailed description")
    screenshot_data: Optional[str] = Field(None, description="Optional base64 screenshot snippet")


class DevNote(DevNoteCreate):
    id: str
    created_at: str
    resolved: bool = False


class DevNoteUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    resolved: Optional[bool] = None


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_notes: dict[str, DevNote] = {}

# ---------------------------------------------------------------------------
# Log file writer
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).resolve().parent.parent.parent  # project root
_LOG_FILE = _LOG_DIR / "dev_notes.log"


def _write_log_file() -> None:
    """Write all unresolved notes to the log file in a structured,
    AI-consumable format."""
    unresolved = [n for n in _notes.values() if not n.resolved]
    # Sort by priority then page
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unresolved.sort(key=lambda n: (priority_order.get(n.priority, 2), n.page))

    lines = [
        "# ImmoManager Pro — Developer Notes",
        f"# Generated: {datetime.utcnow().isoformat()}Z",
        f"# Total unresolved: {len(unresolved)}",
        "",
    ]

    for note in unresolved:
        lines.append(f"## [{note.priority.upper()}] [{note.category}] {note.title}")
        lines.append(f"   Location: page={note.page}" + (f", component={note.component}" if note.component else "") + (f", selector={note.selector}" if note.selector else ""))
        lines.append(f"   Created: {note.created_at}")
        lines.append(f"   ID: {note.id}")
        if note.description:
            for desc_line in note.description.split("\n"):
                lines.append(f"   > {desc_line}")
        lines.append("")

    _LOG_FILE.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Dev notes log written to %s (%d unresolved notes)", _LOG_FILE, len(unresolved))


def _write_json_export() -> str:
    """Write a JSON export of all notes and return the path."""
    export_path = _LOG_DIR / "dev_notes.json"
    all_notes = [n.model_dump() if hasattr(n, "model_dump") else n.dict() for n in _notes.values()]
    export_path.write_text(json.dumps(all_notes, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(export_path)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[DevNote])
def list_dev_notes(
    page: str | None = Query(None),
    category: str | None = Query(None),
    priority: str | None = Query(None),
    resolved: bool | None = Query(None),
) -> list[DevNote]:
    results = list(_notes.values())
    if page:
        results = [n for n in results if n.page == page]
    if category:
        results = [n for n in results if n.category == category]
    if priority:
        results = [n for n in results if n.priority == priority]
    if resolved is not None:
        results = [n for n in results if n.resolved == resolved]
    return results


@router.post("", response_model=DevNote, status_code=status.HTTP_201_CREATED)
def create_dev_note(payload: DevNoteCreate) -> DevNote:
    note = DevNote(
        id=str(uuid4()),
        created_at=datetime.utcnow().isoformat() + "Z",
        **payload.model_dump(),
    )
    _notes[note.id] = note
    _write_log_file()
    return note


@router.get("/export")
def export_dev_notes():
    """Export all notes as JSON and return the file path + content."""
    path = _write_json_export()
    all_notes = [n.model_dump() if hasattr(n, "model_dump") else n.dict() for n in _notes.values()]
    return {"path": path, "count": len(all_notes), "notes": all_notes}


@router.get("/log-content")
def get_log_content():
    """Return the current log file content (for preview)."""
    _write_log_file()
    if _LOG_FILE.exists():
        return {"content": _LOG_FILE.read_text(encoding="utf-8")}
    return {"content": ""}


@router.get("/{note_id}", response_model=DevNote)
def get_dev_note(note_id: str) -> DevNote:
    if note_id not in _notes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dev note not found")
    return _notes[note_id]


@router.patch("/{note_id}", response_model=DevNote)
def update_dev_note(note_id: str, payload: DevNoteUpdate) -> DevNote:
    if note_id not in _notes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dev note not found")
    note = _notes[note_id]
    updates = payload.model_dump(exclude_unset=True)
    updated = note.model_copy(update=updates)
    _notes[note_id] = updated
    _write_log_file()
    return updated


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dev_note(note_id: str) -> None:
    if note_id not in _notes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dev note not found")
    del _notes[note_id]
    _write_log_file()


@router.post("/{note_id}/resolve", response_model=DevNote)
def resolve_dev_note(note_id: str) -> DevNote:
    if note_id not in _notes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dev note not found")
    note = _notes[note_id]
    updated = note.model_copy(update={"resolved": True})
    _notes[note_id] = updated
    _write_log_file()
    return updated
