"""Simple synchronous event bus for plugin communication.

Events are strings like 'entity.created', 'auth.login', etc.
Handlers are callables that receive (event_name, **kwargs).
"""

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[..., Any]

_handlers: dict[str, list[EventHandler]] = defaultdict(list)


def subscribe(event: str, handler: EventHandler) -> None:
    """Subscribe a handler to an event."""
    _handlers[event].append(handler)
    logger.debug("Event handler registered: %s -> %s", event, handler.__name__)


def unsubscribe(event: str, handler: EventHandler) -> None:
    """Unsubscribe a handler from an event."""
    try:
        _handlers[event].remove(handler)
    except ValueError:
        pass


def emit(event: str, **kwargs) -> None:
    """Emit an event, calling all subscribed handlers synchronously."""
    for handler in _handlers.get(event, []):
        try:
            handler(event, **kwargs)
        except Exception:
            logger.exception("Error in event handler %s for event %s", handler.__name__, event)


def clear() -> None:
    """Remove all event handlers (for testing)."""
    _handlers.clear()
