"""Explicit offline normalization in the caller's transaction, never replay."""

from sqlalchemy import and_, func, select

from .history_crypto import ring_for
from .history_store import EVENT, HEAD, RUN, SQLIntegrationHistoryStore
from .history_types import HistoryError, HistoryLimits
from .history_validation import check_deadline, validate_history_journal


def mark_restored_unconfirmed(connection, configuration, *, deadline=None, limits=None):
    """Validate first, then append bounded uncertainty events; never commit.

    Caller guarantees offline exclusive access. SQLAlchemy Connection is used
    for writes; sqlite3 Connection remains supported by the read-only validator.
    Repeated calls return zero. No provider, auth or sessionfactory is invoked.
    """
    limits = limits or HistoryLimits()
    if not validate_history_journal(connection, configuration, deadline=deadline, limits=limits):
        return 0
    if not hasattr(connection, "dialect"):
        raise HistoryError("HISTORY_NOT_CONFIGURED")
    journal = SQLIntegrationHistoryStore(None, keyring=ring_for(configuration), limits=limits)
    count = 0
    for identifier in connection.execute(select(HEAD.c.integration_id).order_by(HEAD.c.integration_id)).scalars():
        check_deadline(deadline)
        head = dict(connection.execute(select(HEAD).where(HEAD.c.integration_id == identifier).with_for_update()).mappings().one())
        after = 0
        while True:
            latest = select(func.max(EVENT.c.event_number)).where(EVENT.c.run_id == RUN.c.id).correlate(RUN).scalar_subquery()
            run = connection.execute(select(RUN).join(EVENT, and_(EVENT.c.run_id == RUN.c.id, EVENT.c.event_number == latest)).where(
                RUN.c.integration_id == identifier, RUN.c.run_sequence > after, EVENT.c.state.in_(["accepted", "execution_started"])).order_by(RUN.c.run_sequence).limit(1)).mappings().first()
            if run is None:
                break
            check_deadline(deadline)
            previous = journal._events(connection, run)[-1][0]
            result = {"success": False, "message": "Das ursprüngliche Ergebnis ist nach Wiederherstellung nicht bestätigt. Vor einer Wiederholung prüfen.",
                "details": {"status": "outcome_unconfirmed", "code": "database_restore", "retry_automatically": False}}
            event = journal._append(connection, run, head, "outcome_uncertain", {"response": result, "schema": {"version": 1, "reason": "offline_restore"}}, previous, deadline=deadline)
            head["event_sequence"] = event["journal_sequence"]
            after = run["run_sequence"]
            count += 1
    return count
