"""The issued (finalized) version of a period's utility statements.

Finalizing stamps every statement of the period with one SHA-256 hash over
their content. The hash proves later that nothing changed: not by regeneration,
not by edits of contracts, meters or costs (the rows are stored, the shown
document is frozen) and not by a snapshot import. Corrections are new periods
that name the version they correct; the corrected version stays as issued.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

# Periods whose statements are issued and must not change any more.
FINAL_STATUSES = frozenset({"finalized", "delivered", "disputed", "corrected"})
EDITABLE_STATUSES = frozenset({"draft", "review"})


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def json_safe(value: Any) -> Any:
    """Tuples to lists, dates to ISO strings: what JSON storage gives back."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return _iso(value)


def statement_snapshot_hash(statements: Iterable[Any]) -> str:
    """Deterministic hash over the content of a period's statements.

    Statements finalized before the document was frozen hash as they always
    did (id, parties, amounts, lines); newer ones also cover usage period,
    advance sections, revision and the frozen document.
    """
    payload = []
    for s in sorted(statements, key=lambda s: s.id):
        entry: dict[str, Any] = {
            "id": s.id,
            "unit_id": s.unit_id,
            "contract_id": s.contract_id,
            "total_cost": float(s.total_cost),
            "advance_paid": float(s.advance_paid),
            "balance": float(s.balance),
            "line_items": s.line_items or [],
        }
        if getattr(s, "final_document", None) is not None:
            entry.update({
                "party": s.party,
                "usage_start": _iso(s.usage_start),
                "usage_end": _iso(s.usage_end),
                "usage_days": s.usage_days,
                "revision": s.revision,
                "advance_sections": s.advance_sections or [],
                "final_document": s.final_document,
            })
        payload.append(entry)
    raw = json.dumps(json_safe(payload), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def final_version_problems(period: Any, statements: list[Any]) -> list[str]:
    """Why the stored statements of a finalized period are not the issued version (empty: intact)."""
    if period.status not in FINAL_STATUSES:
        return []
    stamped = [s for s in statements if s.snapshot_hash]
    if not stamped:
        return []  # finalized before hashes existed: nothing to compare with
    name = getattr(period, "label", None) or period.id
    problems = []
    if len(stamped) != len(statements):
        problems.append(f"{name}: {len(statements) - len(stamped)} Einzelabrechnung(en) ohne finalisierte Fassung")
    hashes = {s.snapshot_hash for s in stamped}
    if len(hashes) != 1 or statement_snapshot_hash(statements) not in hashes:
        problems.append(f"{name}: Inhalt weicht von der finalisierten Fassung ab")
    return problems
