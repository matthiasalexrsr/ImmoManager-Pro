"""Optional real PostgreSQL cache isolation; IMMO_TEST_POSTGRES_ADMIN_URL opts in."""

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401
from test_read_cache_concurrency import CacheBase, CacheRow, cache  # noqa: F401

from backend import concurrency


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"])
def test_existing_postgres_read_transaction_obeys_its_isolation(postgres, cache, isolation):  # noqa: F811
    engine, _ = postgres
    CacheBase.metadata.create_all(engine)
    with Session(engine) as writer:
        writer.add(CacheRow(id=1, value=1))
        writer.commit()
    reads = engine.execution_options(isolation_level=isolation)
    calls = []

    @concurrency.one_at_a_time
    def report(db):
        calls.append(1)
        return {"value": db.scalar(select(CacheRow.value))}

    def fresh():
        with Session(reads) as db:
            return report(db)

    with Session(reads) as snapshot:
        assert snapshot.scalar(select(CacheRow.value)) == 1
        assert fresh() == fresh() == {"value": 1}
        if isolation == "READ COMMITTED":
            assert len(calls) == 1, "ordinary PostgreSQL read transactions still share hits"
        else:
            assert len(calls) == 2, "repeatable snapshots do not publish shared results"
        with Session(engine) as writer:
            writer.execute(update(CacheRow).values(value=2))
            writer.commit()
        assert fresh() == {"value": 2}
        assert report(snapshot) == {"value": 2 if isolation == "READ COMMITTED" else 1}
        assert fresh() == {"value": 2}


def test_postgres_savepoints_keep_outer_uncommitted_writes_private(postgres, cache):  # noqa: F811
    engine, _ = postgres
    CacheBase.metadata.create_all(engine)
    with Session(engine) as writer:
        writer.add(CacheRow(id=1, value=1))
        writer.commit()

    @concurrency.one_at_a_time
    def report(db):
        return {"value": db.scalar(select(CacheRow.value))}

    def fresh():
        with Session(engine) as db:
            return report(db)

    for finish in ("commit", "rollback"):
        with Session(engine) as writer:
            writer.execute(update(CacheRow).values(value=1))
            writer.commit()
        assert fresh() == {"value": 1}
        with Session(engine) as writer:
            writer.execute(update(CacheRow).values(value=2))
            nested = writer.begin_nested()
            writer.execute(update(CacheRow).values(value=3))
            getattr(nested, finish)()
            expected = 3 if finish == "commit" else 2
            assert fresh() == {"value": 1}
            assert report(writer) == {"value": expected}
            assert fresh() == {"value": 1}
            writer.commit()
        assert fresh() == {"value": expected}
