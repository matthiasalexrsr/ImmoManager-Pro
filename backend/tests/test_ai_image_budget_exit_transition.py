"""Own child lookup loss can precede its waitable exit; live roots stay closed.

Controlled transitions do not identify the exact syscall or errno of Native17.
"""

import errno
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.services.e_invoice import image_budget as budgets
from backend.services.e_invoice import validator
from backend.tests import test_ai_image_budget as budget_cases
from backend.tests import test_ai_image_budget_exit as exit_cases
from backend.tests.test_ai_image_budget_exit import Owned

base_owned = exit_cases.owned


@pytest.fixture
def owned(base_owned, monkeypatch):
    monkeypatch.setattr(budgets, "time", SimpleNamespace(monotonic=lambda: 100.0))
    base_owned[-1].deadline = 101.0
    return base_owned


def begin_lookup_loss(root, state, kind):
    def lose():
        state.group_failure = (
            ProcessLookupError(errno.ESRCH, "controlled disappearing own root")
            if kind == "os"
            else budgets.psutil.NoSuchProcess(root.pid)
        )

    root.on_running = lose


@pytest.mark.parametrize("kind", ["os", "psutil"])
@pytest.mark.parametrize("code", [0, 23])
def test_own_exit_transition_is_confirmed_with_bounded_wait_before_reused_identity(owned, monkeypatch, kind, code):
    root, _, raw, state, budget = owned
    waits = []
    begin_lookup_loss(root, state, kind)

    def complete(*, timeout):
        assert 0 < timeout <= 0.05
        waits.append(timeout)
        state.completed, state.reaped, state.returncode = True, True, code
        root.created = 99  # The old identity must never be touched after our wait completes.
        return code

    monkeypatch.setattr(raw, "wait", complete)
    budget.check()
    assert len(waits) == 1 and raw.poll() == code
    assert root.pid not in budget.known
    budget.close()
    assert not root.killed


@pytest.mark.parametrize("failure", ["timeout", "permission", "lookup", "no_exit_status"])
def test_lookup_loss_without_confirmed_own_completion_remains_closed(owned, monkeypatch, failure):
    root, _, raw, state, budget = owned
    begin_lookup_loss(root, state, "os")

    def incomplete(*, timeout):
        assert 0 < timeout <= 0.05
        if failure == "timeout":
            raise subprocess.TimeoutExpired("controlled-owned-child", timeout)
        if failure == "permission":
            raise PermissionError(errno.EPERM, "controlled wait failure")
        if failure == "lookup":
            raise ProcessLookupError(errno.ESRCH, "controlled missing wait status")
        return None

    monkeypatch.setattr(raw, "wait", incomplete)
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    assert not state.completed and not state.reaped
    budget.close()
    assert root.killed


def test_live_root_access_denial_does_not_trigger_exit_wait(owned, monkeypatch):
    root, _, raw, state, budget = owned
    state.group_failure = budgets.psutil.AccessDenied(root.pid)
    monkeypatch.setattr(raw, "wait", lambda **kw: pytest.fail("AccessDenied is no missing-root transition"))
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    budget.close()
    assert root.killed and not state.reaped


def test_changed_root_identity_does_not_trigger_exit_wait(owned, monkeypatch):
    root, _, raw, _, budget = owned
    root.created = 99
    monkeypatch.setattr(raw, "wait", lambda **kw: pytest.fail("Changed identity must fail directly"))
    with pytest.raises(budgets.ImageBudgetError, match="identity changed"):
        budget.check()
    budget.close()
    assert not root.killed


def test_root_completion_preserves_known_descendant_rss_enforcement(owned, monkeypatch):
    root, processes, raw, state, budget = owned
    descendant = Owned(101)
    descendant.created = 11
    processes[101] = descendant
    root.descendants = [descendant]
    budget.check()
    begin_lookup_loss(root, state, "os")
    descendant.rss = budgets.MEMORY_BYTES + 1

    def complete(*, timeout):
        assert 0 < timeout <= 0.05
        state.completed, state.reaped = True, True
        return 0

    monkeypatch.setattr(raw, "wait", complete)
    with pytest.raises(budgets.ImageBudgetError, match="exceeds"):
        budget.check()
    budget.close()
    assert descendant.killed and not root.killed


def test_descendant_denial_never_becomes_a_root_exit_wait(owned, monkeypatch):
    root, processes, raw, state, budget = owned
    descendant = Owned(101)
    descendant.created = 11
    processes[101] = descendant
    root.descendants = [descendant]
    budget.check()
    monkeypatch.setattr(raw, "wait", lambda **kw: pytest.fail("Never resolve a descendant error by root wait"))
    monkeypatch.setattr(descendant, "memory_info", lambda: (_ for _ in ()).throw(budgets.psutil.AccessDenied(101)))
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    budget.close()
    assert descendant.killed and root.killed and not state.reaped


def test_failed_live_cleanup_permission_is_not_silently_accepted(owned, monkeypatch):
    root, _, _, state, budget = owned

    def denied():
        raise PermissionError(errno.EPERM, "controlled own live cleanup failure")

    monkeypatch.setattr(root, "kill", denied)
    with pytest.raises(PermissionError):
        budget.close()
    assert not state.completed and not state.reaped


@pytest.mark.parametrize("deadline", [None, 99.0, 100.0, float("nan"), float("inf")])
def test_missing_expired_or_unusable_deadline_does_not_add_any_wait(owned, monkeypatch, deadline):
    root, _, raw, state, budget = owned
    budget.deadline = deadline
    begin_lookup_loss(root, state, "os")
    monkeypatch.setattr(raw, "wait", lambda **kw: pytest.fail("No safe remaining time"))
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    budget.close()
    assert root.killed and not state.reaped


def test_remaining_time_less_than_fifty_ms_caps_the_single_confirmation(owned, monkeypatch):
    root, _, raw, state, budget = owned
    budget.deadline = 100.012
    begin_lookup_loss(root, state, "os")
    calls = []

    def complete(*, timeout):
        calls.append(timeout)
        state.completed, state.reaped = True, True
        return 0

    monkeypatch.setattr(raw, "wait", complete)
    budget.check()
    assert calls == [pytest.approx(0.012)]
    assert root.pid not in budget.known and raw.poll() == 0


def test_wait_result_without_consistent_owned_poll_is_rejected(owned, monkeypatch):
    root, _, raw, state, budget = owned
    begin_lookup_loss(root, state, "os")
    monkeypatch.setattr(raw, "wait", lambda **kw: 0)
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    budget.close()
    assert root.killed and not state.completed


def test_confirmation_after_original_deadline_is_not_accepted(owned, monkeypatch):
    root, _, raw, state, budget = owned
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(budgets, "time", SimpleNamespace(monotonic=lambda: clock.now))
    begin_lookup_loss(root, state, "os")

    def completed_late(*, timeout):
        clock.now = 101.001
        state.completed, state.reaped = True, True
        root.created = 99  # Cleanup must not kill a reused identity even on rejection.
        return 0

    monkeypatch.setattr(raw, "wait", completed_late)
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    budget.close()
    assert not root.killed


@pytest.mark.parametrize("bad_code", [True, None])
def test_non_integer_exit_status_is_not_confirmed(owned, monkeypatch, bad_code):
    root, _, raw, state, budget = owned
    begin_lookup_loss(root, state, "os")

    def malformed(*, timeout):
        state.completed = True
        return bad_code

    monkeypatch.setattr(raw, "wait", malformed)
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()


def test_owned_context_preserves_deadline_in_constructor_and_cleanup(tmp_path, monkeypatch):
    calls: list[object] = []

    class Budget:
        def __init__(self, process, **kwargs):
            calls.append((process, kwargs))

        def release(self, profile):
            calls.append(profile)

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(budgets, "ImageBudget", Budget)
    process = object()
    with budgets.owned_image_budget(process, tmp_path, max_processes=4, deadline=123.45):
        pass
    assert calls == [(process, {"max_processes": 4, "deadline": 123.45}), tmp_path, "closed"]


@pytest.mark.parametrize("mode", ["image", "document"])
def test_validator_forwards_its_original_deadline_into_the_owned_monitor(tmp_path, monkeypatch, mode):
    state = budget_cases.fake_transport(monkeypatch)
    monkeypatch.setattr(validator, "time", SimpleNamespace(monotonic=lambda: 100.0))
    calls: list[object] = []

    class Monitor:
        def __init__(self, process, **kwargs):
            calls.append(kwargs)

        def release(self, profile):
            pass

        def check(self):
            pass

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(budgets, "ImageBudget", Monitor)
    assert validator._run([sys.executable], tmp_path, resource_mode=mode, timeout_seconds=30) == (0, "", "")
    assert calls == [{"max_processes": 2, "deadline": 130.0}, "closed"]
    assert state.closed
