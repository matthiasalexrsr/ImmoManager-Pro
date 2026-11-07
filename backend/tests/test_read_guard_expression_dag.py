"""Bound read-guard work by SQL node identities without weakening write evidence."""

from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, func, literal, select, text, update
from test_request_read_connection import RequestRow
from test_request_read_connection import pool as pool

from backend import concurrency, dependencies


@pytest.fixture
def guard(pool, monkeypatch):
    """Capture the actual public-event callback on a real owned request connection."""
    _, registry, target = pool
    registered = []
    listen = event.listen

    def observe(connection, name, function, *args, **kwargs):
        if name == "before_cursor_execute" and function.__module__ == dependencies.__name__:
            registered.append(function)
        return listen(connection, name, function, *args, **kwargs)

    monkeypatch.setattr(event, "listen", observe)
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        assert len(registered) == 1
        callback = registered[0]
        connection = db.connection()

        def inspect(statement, *, diagnostic=None, compiled=True):
            context = SimpleNamespace(compiled=SimpleNamespace(statement=statement) if compiled else None,
                execution_options={"request_read_release_check": diagnostic})
            callback(connection, None, "controlled compiled expression", (), context, False)

        yield inspect, db, target
    finally:
        dependencies.end_request_scope(token)


def test_shared_real_sql_dag_expands_each_identity_only_once_per_guard_call(guard, monkeypatch):
    inspect, db, _ = guard
    shared = select(func.lower(literal("READ"))).scalar_subquery()
    statement = select(shared.label("first"), shared.label("second")).where(shared == "read")
    expansions: Counter[int] = Counter()
    get_children = shared.get_children

    def children(**options):
        expansions[id(shared)] += 1
        return get_children(**options)

    monkeypatch.setattr(shared, "get_children", children)
    before = concurrency._version
    inspect(statement)
    assert not db.info.get("cache_pending_write")
    assert concurrency._version == before
    assert expansions[id(shared)] == 1, "The same live SQL subgraph was expanded repeatedly"
    # No cross-statement memoization: the same graph must be traversed anew.
    inspect(select(shared.label("third"), shared.label("fourth")))
    assert expansions[id(shared)] == 2
    assert not db.info.get("cache_pending_write")


@pytest.mark.parametrize("kind", ["dml", "text", "unknown_function", "qualified_function", "for_update"])
def test_unsafe_shared_or_nested_nodes_keep_the_request_transaction_private(guard, kind):
    inspect, db, target = guard
    shared: Any
    if kind == "dml":
        changed = update(RequestRow).values(value=9).returning(RequestRow.value).cte("guard_changed")
        shared = select(changed.c.value).scalar_subquery()
    elif kind == "text":
        shared = select(text("42")).scalar_subquery()
    elif kind == "unknown_function":
        shared = func.controlled_unknown_read_guard(literal(1))
    elif kind == "qualified_function":
        shared = func.private_schema.lower(literal("READ"))
    else:
        shared = select(RequestRow.value).with_for_update().scalar_subquery()
    before = concurrency._version
    transaction = db.get_transaction()
    inspect(select(shared.label("left"), shared.label("right")))
    assert db.info.get("cache_pending_write")
    assert concurrency._version != before
    assert not dependencies.release_request_read_connection(target)
    assert db.get_transaction() is transaction and transaction.is_active


@pytest.mark.parametrize("mutation", ["function_name", "function_package", "locking_read", "dml_marker"])
def test_reused_live_nodes_are_rechecked_in_a_second_statement_after_mutation(guard, mutation):
    inspect, db, target = guard
    function = func.lower(literal("READ"))
    nested = select(function).scalar_subquery()
    element: Any = nested.element
    inspect(select(nested.label("one"), nested.label("two")))
    assert not db.info.get("cache_pending_write")
    if mutation == "function_name":
        function.name = "controlled_unknown_read_guard"
    elif mutation == "function_package":
        function.packagenames = ("private_schema",)
    elif mutation == "locking_read":
        element._for_update_arg = select(literal(1)).with_for_update()._for_update_arg
    else:
        element.is_dml = True
    before = concurrency._version
    inspect(select(nested.label("again"), nested.label("same_identity")))
    assert db.info.get("cache_pending_write")
    assert concurrency._version != before
    assert not dependencies.release_request_read_connection(target)


@pytest.mark.parametrize("diagnostic", [None, True, "request_read_release_check"])
def test_unknown_function_cannot_claim_the_private_diagnostic_marker(guard, diagnostic):
    inspect, db, target = guard
    function = func.controlled_unknown_read_guard(literal(1))
    inspect(select(function, function), diagnostic=diagnostic)
    assert db.info.get("cache_pending_write")
    assert not dependencies.release_request_read_connection(target)


def test_only_the_existing_server_owned_diagnostic_marker_keeps_its_exception(guard):
    inspect, db, _ = guard
    function = func.controlled_server_read_diagnostic(literal(1))
    before = concurrency._version
    inspect(select(function, function), diagnostic=dependencies._READ_RELEASE_CHECK)
    assert not db.info.get("cache_pending_write")
    assert concurrency._version == before


def test_uncompiled_sql_remains_unknown_even_when_the_text_looks_like_a_select(guard):
    inspect, db, target = guard
    inspect(None, compiled=False)
    assert db.info.get("cache_pending_write")
    assert not dependencies.release_request_read_connection(target)
