"""An owned completed root may race an RSS permission query; live roots fail closed.

These controlled races do not establish the cause of Native16's unobserved DOCX failure.
"""

import errno

import pytest

from backend.services.e_invoice import image_budget as budgets
from backend.tests.test_ai_image_budget_exit import Owned
from backend.tests.test_ai_image_budget_exit import owned as owned


@pytest.mark.parametrize("denial", ["psutil", "os"])
@pytest.mark.parametrize("exit_code", [0, 23])
def test_rss_denial_after_confirmed_owned_root_exit_preserves_exit_code(owned, monkeypatch, denial, exit_code):
    root, _, raw, state, budget = owned

    def finish_and_deny():
        state.completed = True
        state.returncode = exit_code
        if denial == "psutil":
            raise budgets.psutil.AccessDenied(root.pid)
        raise PermissionError(errno.EPERM, "controlled race")

    monkeypatch.setattr(root, "memory_info", finish_and_deny)
    budget.check()
    assert state.reaped and root.pid not in budget.known
    assert raw.poll() == exit_code
    budget.close()
    assert not root.killed


@pytest.mark.parametrize("denial", ["psutil", "os"])
def test_identical_rss_denial_while_owned_root_is_live_still_fails_closed(owned, monkeypatch, denial):
    root, _, _, state, budget = owned

    def denied():
        if denial == "psutil":
            raise budgets.psutil.AccessDenied(root.pid)
        raise PermissionError(errno.EPERM, "controlled live denial")

    monkeypatch.setattr(root, "memory_info", denied)
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    assert not state.completed and not state.reaped
    budget.close()
    assert root.killed


def test_finished_root_does_not_hide_live_descendant_access_denial(owned, monkeypatch):
    root, processes, _, state, budget = owned
    descendant = Owned(101)
    descendant.created = 11
    processes[101] = descendant
    root.descendants = [descendant]
    budget.check()
    state.completed = True

    def denied():
        raise budgets.psutil.AccessDenied(descendant.pid)

    monkeypatch.setattr(descendant, "memory_info", denied)
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    budget.close()
    assert descendant.killed and not root.killed


def test_changed_identity_before_a_denial_is_never_accepted_as_completion(owned, monkeypatch):
    root, _, _, state, budget = owned

    def changed():
        root.created = 99
        state.completed = True

    root.on_running = changed
    with pytest.raises(budgets.ImageBudgetError, match="identity changed"):
        budget.check()
    budget.close()
    assert not root.killed


def test_confirmed_root_exit_still_enforces_known_descendant_memory(owned, monkeypatch):
    root, processes, _, state, budget = owned
    descendant = Owned(101)
    descendant.created = 11
    processes[101] = descendant
    root.descendants = [descendant]
    budget.check()

    def root_denial():
        state.completed = True
        raise budgets.psutil.AccessDenied(root.pid)

    monkeypatch.setattr(root, "memory_info", root_denial)
    descendant.rss = budgets.MEMORY_BYTES + 1
    with pytest.raises(budgets.ImageBudgetError, match="exceeds"):
        budget.check()
    budget.close()
    assert descendant.killed and not root.killed
