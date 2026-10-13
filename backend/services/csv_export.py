"""Keep untrusted spreadsheet text literal; CSV writers still own field quoting."""

from decimal import Decimal
from typing import Any


def spreadsheet_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if not isinstance(value, (int, float, Decimal)) and (
        text.lstrip()[:1] in ("=", "+", "-", "@") or text[:1] in ("\t", "\r", "\n")
    ):
        return "'" + text
    return text
