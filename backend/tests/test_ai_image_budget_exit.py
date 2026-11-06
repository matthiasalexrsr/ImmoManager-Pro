"""A completed owned process must be reaped before a stale group is inspected."""
import errno
import os
import signal
from io import StringIO
from types import SimpleNamespace

import pytest

from backend.services import assistant_provider_process as transport
from backend.services.e_invoice import image_budget as budgets


class Owned:
    def __init__(self, pid=100):
        self.pid, self.created, self.group, self.rss = pid, 10.0, 100, 100
        self.running = True
        self.killed = False
        self.descendants = []
        self.on_running = lambda: None
        self.on_children = lambda: None

    def ppid(self):
        return os.getpid()

    def create_time(self):
        return self.created

    def is_running(self):
        self.on_running()
        return self.running

    def children(self, recursive=True):
        self.on_children()
        return self.descendants

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def kill(self):
        self.killed = True
        self.running = False


@pytest.fixture
def owned(monkeypatch):
    root = Owned()
    processes = {100: root}
    state = SimpleNamespace(completed=False, reaped=False, group_failure=None, returncode=0)

    def poll():
        if state.completed:
            state.reaped = True
            return state.returncode
        return None

    def group(pid):
        if pid == root.pid and state.group_failure is not None:
            raise state.group_failure
        return processes[pid].group
    raw = SimpleNamespace(pid=root.pid, poll=poll, wait=lambda timeout: poll(),
        stdin=StringIO(), stdout=StringIO(), stderr=StringIO())
    monkeypatch.setattr(budgets, 'os', SimpleNamespace(name='posix', getpid=os.getpid, getpgid=group))
    monkeypatch.setattr(budgets.psutil, 'Process', lambda pid: processes[pid])
    budget = budgets.ImageBudget(raw)
    return root, processes, raw, state, budget


def test_completed_root_is_reaped_before_any_stale_or_reused_pid_query(owned):
    root, _, _, state, budget = owned
    state.completed = True
    state.group_failure = AssertionError('Never inspect a reaped/reusable PID')
    root.on_running = lambda: pytest.fail('Never query old psutil identity after confirmed completion')
    budget.check()
    assert state.reaped and root.pid not in budget.known
    budget.close()
    assert not root.killed


@pytest.mark.parametrize('code', [-9, 1, 23])
def test_completed_nonzero_exit_is_preserved_for_callers(owned, code):
    root, _, raw, state, budget = owned
    state.completed, state.returncode = True, code
    state.group_failure = AssertionError('Never inspect completed root')
    budget.check()
    assert raw.poll() == code and root.pid not in budget.known
    budget.close()
    assert not root.killed


@pytest.mark.parametrize('stage', ['is_running', 'children'])
@pytest.mark.parametrize('error', [ProcessLookupError(errno.ESRCH, 'finished'), budgets.psutil.NoSuchProcess(100)])
def test_root_exit_between_probe_steps_requires_owned_completion(owned, stage, error):
    root, _, _, state, budget = owned

    def finish():
        state.completed = True
        if stage == 'is_running':
            state.group_failure = error
        else:
            raise error
    if stage == 'is_running':
        root.on_running = finish
    else:
        root.on_children = finish
    budget.check()
    assert state.reaped and root.pid not in budget.known
    budget.close()
    assert not root.killed


def test_reaped_root_still_measures_and_closes_known_descendants(owned):
    root, processes, _, state, budget = owned
    descendant = Owned(101)
    descendant.created = 11
    processes[101] = descendant
    root.descendants = [descendant]
    budget.check()
    state.completed = True
    state.group_failure = ProcessLookupError(errno.ESRCH, 'root finished')
    budget.check()
    assert root.pid not in budget.known and descendant.pid in budget.known
    descendant.rss = budgets.MEMORY_BYTES + 1
    with pytest.raises(budgets.ImageBudgetError, match='exceeds'):
        budget.check()
    budget.close()
    assert descendant.killed and not root.killed


@pytest.mark.parametrize('error', [ProcessLookupError(errno.ESRCH, 'unmeasurable live root'),
    budgets.psutil.NoSuchProcess(100), PermissionError(errno.EPERM, 'permission denied')])
def test_unmeasurable_or_denied_live_root_still_fails_closed(owned, error):
    root, _, _, state, budget = owned
    state.group_failure = error
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    assert not state.completed and not state.reaped
    budget.close()
    assert root.killed


def test_changed_live_identity_is_not_mistaken_for_successful_exit(owned):
    root, _, _, state, budget = owned
    root.created = 99
    with pytest.raises(budgets.ImageBudgetError, match='identity changed'):
        budget.check()
    budget.close()
    assert not state.reaped and not root.killed


def test_reaped_root_cannot_hide_permission_failure_of_live_owned_descendant(owned, monkeypatch):
    root, processes, _, state, budget = owned
    descendant = Owned(101)
    descendant.created = 11
    processes[101] = descendant
    root.descendants = [descendant]
    budget.check()
    state.completed = True

    def denied():
        raise budgets.psutil.AccessDenied(descendant.pid)
    monkeypatch.setattr(descendant, 'memory_info', denied)
    with pytest.raises(budgets.ImageBudgetError, match='measurement failed'):
        budget.check()
    budget.close()
    assert descendant.killed


def test_completed_root_is_reaped_before_generic_group_cleanup(monkeypatch, owned):
    root, _, raw, state, budget = owned
    attempted = []

    def group_signal(pid, sig):
        assert pid == root.pid
        attempted.append((pid, sig, state.reaped))
        if not state.reaped:
            # Darwin killpg can find only zombies and return EPERM. We must
            # reap the confirmed owned process, rather than ignore permissions.
            raise PermissionError(errno.EPERM, 'only an unreaped zombie remains')
        raise ProcessLookupError(errno.ESRCH, 'owned group no longer exists')
    monkeypatch.setattr(transport, 'os', SimpleNamespace(name='posix', killpg=group_signal))
    monkeypatch.setattr(signal, 'SIGKILL', 9, raising=False)
    process = transport.CliProcess.__new__(transport.CliProcess)
    process._closed, process.job, process.process, process.readers = False, None, raw, []
    state.completed = True
    state.group_failure = ProcessLookupError(errno.ESRCH, 'zombie has no group lookup')
    try:
        budget.check()
    finally:
        budget.close()
        process.close()
    assert state.reaped and attempted and all(reaped for _, _, reaped in attempted)


def test_generic_cleanup_permission_error_for_live_process_is_not_suppressed(monkeypatch, owned):
    _, _, raw, state, _ = owned

    def denied(*args):
        raise PermissionError(errno.EPERM, 'live owned process cannot be signalled')
    monkeypatch.setattr(transport, 'os', SimpleNamespace(name='posix', killpg=denied))
    process = transport.CliProcess.__new__(transport.CliProcess)
    process._closed, process.job, process.process, process.readers = False, None, raw, []
    with pytest.raises(PermissionError):
        process.close()
    assert not state.completed and not state.reaped
