"""The in-memory store follows the ON DELETE rules of the project tables, like the database.

Deleting a case, an invoice, a booking, a calendar event or a document in memory takes
the project rows that reference it along (CASCADE) or clears their reference (SET NULL),
so a memory store never holds a reference the database would not hold. NO ACTION and
RESTRICT references are guarded by the application before the delete.
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Any

from ..db.maintenance_project_models import PROJECT_TABLES
from ..db.orm_models import Base


@lru_cache(maxsize=1)
def _rules() -> dict[str, tuple[tuple[str, str, str], ...]]:
    """parent table -> ((child table, column, ON DELETE action), ...) for the project tables."""
    found: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for name in PROJECT_TABLES:
        for column in Base.metadata.tables[name].columns:
            for foreign in column.foreign_keys:
                found[foreign.column.table.name].append((name, column.name, (foreign.ondelete or "").upper()))
    return {parent: tuple(children) for parent, children in found.items()}


def plan(raw: dict[str, Any], table: str, key: str) -> list[tuple[str, str, str, str | None]]:
    """What deleting raw[table][key] does to the project rows: ("delete" | "null", table, id, column).

    Deepest rows first, each row once; the row itself is not part of the plan.
    """
    steps: list[tuple[str, str, str, str | None]] = []
    deleted: set[tuple[str, str]] = set()

    def visit(parent: str, parent_key: str) -> None:
        for child, column, action in _rules().get(parent, ()):
            rows = raw.get(child)
            if rows is None or action not in ("CASCADE", "SET NULL"):
                continue
            for child_key, row in list(dict.items(rows)):
                if getattr(row, column, None) != parent_key or (child, child_key) in deleted:
                    continue
                if action == "CASCADE":
                    deleted.add((child, child_key))
                    visit(child, child_key)
                    steps.append(("delete", child, child_key, None))
                else:
                    steps.append(("null", child, child_key, column))

    visit(table, key)
    return [step for step in steps if step[0] == "delete" or (step[1], step[2]) not in deleted]


def apply(raw: dict[str, Any], steps: list[tuple[str, str, str, str | None]], undo: list | None = None) -> None:
    """Carry out a plan on the raw collections; `undo` receives (collection, key, present, old value)."""
    for action, table, key, column in steps:
        rows = raw[table]
        if key not in dict.keys(rows):
            continue
        old = dict.__getitem__(rows, key)
        if undo is not None:
            undo.append((rows, key, True, old))
        if action == "delete":
            dict.__delitem__(rows, key)
        else:
            dict.__setitem__(rows, key, old.model_copy(update={column: None}))


class CascadingDict(dict):
    """A store collection whose deletes apply the project tables' ON DELETE rules."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.raw: dict[str, Any] | None = None

    def bind(self, raw: dict[str, Any]) -> None:
        self.raw = raw

    def __delitem__(self, key: str) -> None:
        if self.raw is not None and key in dict.keys(self):
            apply(self.raw, plan(self.raw, self.name, key))
        super().__delitem__(key)

    def __reduce__(self):            # copies and pickles are plain dicts
        return (dict, (dict(self),))


def parent_tables() -> tuple[str, ...]:
    """Collections whose deletes reach project rows."""
    return tuple(sorted(_rules()))
