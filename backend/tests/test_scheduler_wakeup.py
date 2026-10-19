"""Local wakeup hints accelerate durable jobs without replacing scheduler recovery."""

import asyncio
import threading

import pytest

from backend.config import settings
from backend.services.jobs import scheduler
from backend.services.jobs.core import MemoryJobStore
from backend.storage import InMemoryStore

AsyncEvent = asyncio.Event


@pytest.fixture
def scheduler_setup(monkeypatch):
    jobs = MemoryJobStore(store_factory=InMemoryStore)
    waiting = threading.Event()

    class ObservedEvent(AsyncEvent):
        async def wait(self):
            waiting.set()
            return await super().wait()

    monkeypatch.setattr(settings, "job_scheduler_enabled", True)
    monkeypatch.setattr(scheduler, "get_job_store", lambda: jobs)
    monkeypatch.setattr(scheduler, "default_handlers", lambda: {})
    monkeypatch.setattr(scheduler.asyncio, "Event", ObservedEvent)
    return jobs, waiting


async def reached(event):
    assert await asyncio.to_thread(event.wait, 3), "scheduler did not reach expected state"


async def shutdown(task, stop):
    stop.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_wakeup_dispatches_a_new_assistant_job_without_waiting_for_interval(scheduler_setup, monkeypatch):
    from backend.services import assistant, assistant_runner
    from backend.services.jobs import communication

    jobs, waiting = scheduler_setup
    handled = threading.Event()
    payloads = []

    def handle(ctx):
        payloads.append(ctx.run.payload)
        handled.set()
        return True

    monkeypatch.setattr(scheduler, "default_handlers", lambda: {"assistant.run": handle})
    monkeypatch.setattr(scheduler, "enqueue_due", lambda *_: [])
    monkeypatch.setattr(communication, "recover", lambda *_: None)
    monkeypatch.setattr(assistant_runner, "recover", lambda *_: None)

    async def scenario():
        stop = threading.Event()
        task = asyncio.create_task(scheduler.run_forever(3600, stop))
        try:
            await reached(waiting)
            # FastAPI's synchronous service runs in a request worker thread.
            await asyncio.to_thread(assistant.wake, "fresh-run", "actor-1")
            await reached(handled)
            assert payloads == [{"run_id": "fresh-run", "actor_id": "actor-1"}]
            assert jobs.find("assistant:fresh-run") is not None
        finally:
            await shutdown(task, stop)

    asyncio.run(scenario())


def test_wakeups_during_a_tick_are_retained_and_coalesced(scheduler_setup, monkeypatch):
    _, waiting = scheduler_setup
    started = threading.Event()
    release = threading.Event()
    second_tick = threading.Event()
    calls = []

    def tick(*_):
        calls.append(True)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        else:
            second_tick.set()
        return []

    monkeypatch.setattr(scheduler, "tick", tick)

    async def scenario():
        stop = threading.Event()
        task = asyncio.create_task(scheduler.run_forever(3600, stop))
        try:
            await reached(started)
            for _ in range(50):
                scheduler.request_wakeup()
            # Flush scheduled callbacks while the drain is still in progress.
            await asyncio.sleep(0)
            release.set()
            await reached(second_tick)
            await reached(waiting)
            await asyncio.sleep(0.03)
            assert len(calls) == 2  # no busy loop after consuming the batch
        finally:
            release.set()
            await shutdown(task, stop)

    asyncio.run(scenario())


def test_disabled_scheduler_ignores_wakeup_hints(scheduler_setup, monkeypatch):
    _, waiting = scheduler_setup
    calls = []
    monkeypatch.setattr(scheduler, "tick", lambda *_: calls.append(True))

    async def scenario():
        stop = threading.Event()
        task = asyncio.create_task(scheduler.run_forever(3600, stop))
        try:
            await reached(waiting)
            monkeypatch.setattr(settings, "job_scheduler_enabled", False)
            scheduler.request_wakeup()
            await asyncio.sleep(0.03)
            assert len(calls) == 1
        finally:
            await shutdown(task, stop)

    asyncio.run(scenario())


def test_wakeup_without_an_active_scheduler_does_not_start_a_worker(monkeypatch):
    monkeypatch.setattr(settings, "job_scheduler_enabled", True)

    def unexpected_worker():
        pytest.fail("a wakeup hint must not create a job store or worker")

    monkeypatch.setattr(scheduler, "get_job_store", unexpected_worker)
    assert not scheduler._wakeups
    scheduler.request_wakeup()
    assert not scheduler._wakeups


def test_assistant_enqueue_stays_durable_when_scheduler_is_disabled(scheduler_setup, monkeypatch):
    from backend.services import assistant

    jobs, _ = scheduler_setup
    monkeypatch.setattr(settings, "job_scheduler_enabled", False)
    assistant.wake("disabled-run", "actor-1")
    run = jobs.find("assistant:disabled-run")
    assert run is not None and run.status == "queued"
    assert not scheduler._wakeups


def test_assistant_enqueue_survives_a_failed_wakeup_hint(scheduler_setup, monkeypatch):
    from backend.services import assistant

    jobs, _ = scheduler_setup

    def failed_hint():
        raise RuntimeError("event loop closed during shutdown")

    monkeypatch.setattr(scheduler, "request_wakeup", failed_hint)
    assistant.wake("durable-run", "actor-1")
    run = jobs.find("assistant:durable-run")
    assert run is not None and run.status == "queued"


def test_stop_during_a_tick_exits_without_waiting_for_interval(scheduler_setup, monkeypatch):
    stop = threading.Event()

    def tick(*_):
        stop.set()
        return []

    monkeypatch.setattr(scheduler, "tick", tick)

    async def scenario():
        await asyncio.wait_for(scheduler.run_forever(3600, stop), timeout=3)
        assert not scheduler._wakeups

    asyncio.run(scenario())


def test_cancelled_idle_scheduler_unregisters_wakeup(scheduler_setup, monkeypatch):
    _, waiting = scheduler_setup
    monkeypatch.setattr(scheduler, "tick", lambda *_: [])

    async def scenario():
        stop = threading.Event()
        task = asyncio.create_task(scheduler.run_forever(3600, stop))
        await reached(waiting)
        await shutdown(task, stop)
        assert not scheduler._wakeups
        scheduler.request_wakeup()  # no stale callback into a cancelled loop

    asyncio.run(scenario())


def test_interval_still_recovers_jobs_from_another_process(scheduler_setup, monkeypatch):
    from backend.services import assistant_runner
    from backend.services.jobs import communication

    jobs, waiting = scheduler_setup
    handled = threading.Event()
    recoveries = []

    def handle(ctx):
        handled.set()
        return True

    monkeypatch.setattr(scheduler, "default_handlers", lambda: {"other-job": handle})
    monkeypatch.setattr(scheduler, "enqueue_due", lambda *_: [])
    monkeypatch.setattr(communication, "recover", lambda *_: recoveries.append("communication"))
    monkeypatch.setattr(assistant_runner, "recover", lambda *_: recoveries.append("assistant"))

    async def scenario():
        stop = threading.Event()
        task = asyncio.create_task(scheduler.run_forever(0.03, stop))
        try:
            await reached(waiting)
            # A different process commits this row without a local wakeup hint.
            jobs.enqueue("other-job", "external:1")
            await reached(handled)
            assert recoveries.count("assistant") >= 2
            assert recoveries.count("communication") >= 2
        finally:
            await shutdown(task, stop)

    asyncio.run(scenario())
