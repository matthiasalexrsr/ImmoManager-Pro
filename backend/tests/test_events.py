"""Tests for the event bus module."""

from backend.events import clear, emit, subscribe, unsubscribe


def test_subscribe_and_emit():
    results = []

    def handler(event, **kwargs):
        results.append((event, kwargs))

    subscribe("test.event", handler)
    emit("test.event", foo="bar")

    assert len(results) == 1
    assert results[0] == ("test.event", {"foo": "bar"})
    clear()


def test_unsubscribe():
    results = []

    def handler(event, **kwargs):
        results.append(event)

    subscribe("test.event", handler)
    unsubscribe("test.event", handler)
    emit("test.event")

    assert len(results) == 0
    clear()


def test_unsubscribe_nonexistent():
    def handler(event, **kwargs):
        pass

    # Should not raise
    unsubscribe("nonexistent", handler)
    clear()


def test_emit_handler_exception(caplog):
    def bad_handler(event, **kwargs):
        raise ValueError("boom")

    subscribe("test.event", bad_handler)
    # Should not raise, just log
    emit("test.event")
    assert "Error in event handler" in caplog.text
    clear()


def test_clear():
    def handler(event, **kwargs):
        pass

    subscribe("test.event", handler)
    clear()
    results = []

    def recorder(event, **kwargs):
        results.append(event)

    emit("test.event")
    assert len(results) == 0
