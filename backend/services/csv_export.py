"""Keep untrusted spreadsheet text literal; CSV writers still own field quoting."""

from decimal import Decimal
from typing import Any


def spreadsheet_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    start = 0
    # Spreadsheet importers can discard leading controls/BOM before interpreting
    # a field. Preserve them, but inspect the first meaningful character.
    while start < len(text) and (ord(text[start]) <= 32 or text[start].isspace() or text[start] == "\ufeff"):
        start += 1
    if not isinstance(value, (int, float, Decimal)) and (
        text[start:start + 1] in ("=", "+", "-", "@") or text[:1] in ("\t", "\r", "\n")
    ):
        return "'" + text
    return text
