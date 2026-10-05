"""Run long calculations one after the other.

Reports, the review list and the dashboard figures read thousands of rows. Run
side by side in the server's thread pool they slow each other down many times
over: SQLite gives up Python's GIL for every row it reads and has to queue to get
it back behind the other calculations. One after the other they finish sooner,
also for the one who asked last (dashboard: 13 s side by side, 2 s in a row).
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_HEAVY = threading.RLock()   # re-entrant: a calculation may call another one


def one_at_a_time(func: F) -> F:
    """Decorator for synchronous endpoints and services that read whole tables."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _HEAVY:
            return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
