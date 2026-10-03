"""Prevent implicit writes while repository guards inspect caller-owned state."""

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, Protocol, TypeVar, cast

from sqlalchemy.orm import Session

_P = ParamSpec("_P")
_R = TypeVar("_R")


class _SessionOwner(Protocol):
    db: Session


def no_autoflush_guard(method: Callable[_P, _R]) -> Callable[_P, _R]:
    """Keep preliminary reads from flushing pending facts before validation.

    Explicit flushes and commits retain their usual semantics after validation.
    The context restores the caller's previous autoflush setting on every exit.
    """
    @wraps(method)
    def guarded(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        owner = cast(_SessionOwner, args[0])
        with owner.db.no_autoflush:
            return method(*args, **kwargs)

    return guarded
