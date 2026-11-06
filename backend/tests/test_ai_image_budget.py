"""Image-only RSS sampling, identity checks and pre-parser startup handshake."""
import builtins
import json
import os
import sys
from dataclasses import asdict
from io import StringIO
from types import SimpleNamespace

import pytest

from backend.services.e_invoice import image_budget as budgets
from backend.services.e_invoice import posix_worker, validator


class FakeProcess:
    def __init__(self, pid=100, *, created=10.0, rss=100):
        self.pid, self.created, self.rss = pid, created, rss
        self.running, self.killed, self.group = True, False, 100
        self.descendants = []
        self.error = None

    def ppid(self):
        return os.getpid()

    def create_time(self):
        return self.created

    def is_running(self):
        return self.running

    def children(self, recursive=True):
        assert recursive
        return self.descendants

    def memory_info(self):
        if self.error:
            raise self.error
        return SimpleNamespace(rss=self.rss)

    def kill(self):
        self.killed = True
        self.running = False


@pytest.fixture
def owned(monkeypatch):
    root = FakeProcess()
    processes = {root.pid: root}
    child = SimpleNamespace(pid=root.pid, poll=lambda: None if root.running else 0)
    monkeypatch.setattr(budgets, 'os', SimpleNamespace(
        name='posix', getpid=os.getpid, getpgid=lambda pid: processes[pid].group,
        open=os.open, fdopen=os.fdopen, link=os.link, O_WRONLY=os.O_WRONLY,
        O_CREAT=os.O_CREAT, O_EXCL=os.O_EXCL))
    monkeypatch.setattr(budgets.psutil, 'Process', lambda pid: processes[pid])
    return root, processes, child


def test_initial_sample_precedes_atomic_gate_and_normal_exit(owned, tmp_path):
    root, _, child = owned
    budget = budgets.ImageBudget(child)
    assert not (tmp_path / budgets.READY_FILE).exists()
    budget.release(tmp_path)
    assert (tmp_path / budgets.READY_FILE).read_bytes() == budgets.READY_CONTENT
    assert not (tmp_path / (budgets.READY_FILE + '.pending')).exists()
    root.running = False
    budget.check()
    budget.close()
    assert not root.killed


@pytest.mark.parametrize('error', [budgets.psutil.AccessDenied(100), budgets.psutil.NoSuchProcess(100)])
def test_initial_measurement_failure_never_releases_parser(owned, tmp_path, error):
    root, _, child = owned
    root.error = error
    with pytest.raises(budgets.ImageBudgetError):
        with budgets.owned_image_budget(child, tmp_path, max_processes=2):
            pytest.fail('Parser must not be released')
    assert not (tmp_path / budgets.READY_FILE).exists()
    if isinstance(error, budgets.psutil.AccessDenied):
        assert root.killed


def test_initial_group_escape_closes_retained_descendant_and_root(owned, tmp_path):
    root, processes, child = owned
    escaped = FakeProcess(101, created=11)
    processes[101] = escaped
    escaped.group = 999
    root.descendants = [escaped]
    with pytest.raises(budgets.ImageBudgetError, match='left its owned group'):
        with budgets.owned_image_budget(child, tmp_path, max_processes=2):
            pytest.fail('Initial ownership was not confirmed')
    assert root.killed and escaped.killed and not (tmp_path / budgets.READY_FILE).exists()


@pytest.mark.parametrize('rss', [True, False, -1, 10.5, None])
def test_invalid_rss_measurement_closes_without_parser_release(owned, tmp_path, rss):
    root, _, child = owned
    root.rss = rss
    with pytest.raises(budgets.ImageBudgetError, match='measurement'):
        with budgets.owned_image_budget(child, tmp_path, max_processes=2):
            pytest.fail('Invalid RSS')
    assert root.killed and not (tmp_path / budgets.READY_FILE).exists()


def test_later_measurement_failure_closes_owned_identity(owned, tmp_path):
    root, _, child = owned
    with pytest.raises(budgets.ImageBudgetError, match='measurement failed'):
        with budgets.owned_image_budget(child, tmp_path, max_processes=2) as budget:
            root.error = budgets.psutil.AccessDenied(100)
            budget.check()
    assert root.killed


@pytest.mark.parametrize('rss,allowed', [(budgets.MEMORY_BYTES, True), (budgets.MEMORY_BYTES + 1, False)])
def test_rss_is_measured_in_bytes_against_original_budget(owned, rss, allowed):
    root, _, child = owned
    root.rss = rss
    if allowed:
        budgets.ImageBudget(child).check()
    else:
        with pytest.raises(budgets.ImageBudgetError, match='exceeds'):
            budgets.ImageBudget(child)


def test_aggregate_rss_and_process_count_include_owned_children(owned):
    root, processes, child = owned
    second = FakeProcess(101, created=11, rss=budgets.MEMORY_BYTES)
    root.descendants = [second]
    processes[101] = second
    with pytest.raises(budgets.ImageBudgetError, match='exceeds'):
        budgets.ImageBudget(child)
    assert root.killed and second.killed
    root.running = second.running = True  # Independent next request in this fake tree.
    second.rss = 0
    third = FakeProcess(102, created=11)
    root.descendants.append(third)
    processes[102] = third
    with pytest.raises(budgets.ImageBudgetError, match='exceeds'):
        budgets.ImageBudget(child)


def test_darwin_document_budget_allows_four_owned_processes_and_rejects_five(owned):
    root, processes, child = owned
    for pid in (101, 102, 103):
        descendant = FakeProcess(pid, created=11)
        processes[pid] = descendant
        root.descendants.append(descendant)
    budget = budgets.ImageBudget(child, max_processes=4)
    extra = FakeProcess(104, created=11)
    processes[104] = extra
    root.descendants.append(extra)
    with pytest.raises(budgets.ImageBudgetError, match='exceeds'):
        budget.check()
    budget.close()
    assert all(item.killed for item in processes.values())


def test_foreign_root_is_rejected_before_any_memory_sample(owned):
    root, _, child = owned
    root.group = 999
    root.error = AssertionError('Must not measure foreign process')
    with pytest.raises(budgets.ImageBudgetError, match='ownership'):
        budgets.ImageBudget(child)
    assert not root.killed


def test_disappeared_child_and_short_lived_root_are_not_foreign_measurements(owned):
    root, processes, child = owned
    second = FakeProcess(101, created=11)
    processes[101] = second
    root.descendants = [second]
    budget = budgets.ImageBudget(child)
    second.error = budgets.psutil.NoSuchProcess(101)
    budget.check()
    assert 101 not in budget.known
    root.running = False
    root.descendants = []
    budget.check()
    budget.close()
    assert not root.killed and not second.killed


def test_observed_group_escape_fails_and_closes_only_saved_descendant(owned, tmp_path):
    root, processes, child = owned
    escaped = FakeProcess(101, created=11)
    processes[101] = escaped
    with pytest.raises(budgets.ImageBudgetError, match='left its owned group'):
        with budgets.owned_image_budget(child, tmp_path, max_processes=2) as budget:
            root.descendants = [escaped]
            escaped.group = 999
            budget.check()
    assert root.killed and escaped.killed


def test_pid_reuse_is_never_killed_or_measured(owned):
    root, _, child = owned
    budget = budgets.ImageBudget(child)
    root.created = 99  # This no longer denotes our saved PID identity.
    root.error = AssertionError('Must not measure a reused PID')
    with pytest.raises(budgets.ImageBudgetError, match='identity changed'):
        budget.check()
    budget.close()
    assert not root.killed


def test_preexisting_gate_is_not_overwritten_and_cleanup_still_runs(owned, tmp_path):
    root, _, child = owned
    gate = tmp_path / budgets.READY_FILE
    gate.write_text('preexisting')
    with pytest.raises(FileExistsError):
        with budgets.owned_image_budget(child, tmp_path, max_processes=2):
            pytest.fail('Unverified gate')
    assert root.killed and gate.read_text() == 'preexisting'


def setup_wrapper(tmp_path, monkeypatch):
    folder = tmp_path / 'immo-e-invoice-image-test'
    folder.mkdir()
    called = []
    resources = SimpleNamespace(RLIMIT_AS=1, RLIMIT_CPU=2, RLIMIT_CORE=3, RLIMIT_FSIZE=4,
        RLIMIT_NOFILE=5, RLIM_INFINITY=-1, getrlimit=lambda _: (-1, -1),
        setrlimit=lambda name, value: called.append((name, value)))
    monkeypatch.setitem(sys.modules, 'resource', resources)
    monkeypatch.setattr(posix_worker, 'os', SimpleNamespace(name='posix',
        environ={'E_INVOICE_LIMIT_DIR': str(folder)}, execvpe=lambda *args: called.append(('exec', args))))
    return folder, called


@pytest.mark.parametrize('mode', ['image', 'document'])
def test_image_wrapper_waits_before_exec_and_retains_all_other_limits(tmp_path, monkeypatch, mode):
    folder, called = setup_wrapper(tmp_path, monkeypatch)
    waits = []

    def confirm_monitor(_):
        assert not any(name == 'exec' for name, _ in called)
        waits.append('monitor')
        (folder / budgets.READY_FILE).write_bytes(budgets.READY_CONTENT)
    monkeypatch.setattr(posix_worker.time, 'sleep', confirm_monitor)
    posix_worker.main([str(folder), mode, '30', sys.executable, 'native-parser'])
    assert waits == ['monitor']
    assert called[:-1] == [(2, (30, 30)), (3, (0, 0)),
                          (4, (128 * 1024 * 1024,) * 2), (5, (128, 128))]
    assert called[-1][0] == 'exec'


@pytest.mark.parametrize('content', [None, b'wrong', b''])
def test_missing_or_invalid_monitor_never_executes_parser(tmp_path, monkeypatch, content):
    folder, called = setup_wrapper(tmp_path, monkeypatch)
    if content is not None:
        (folder / budgets.READY_FILE).write_bytes(content)
    clock = iter([0, 6])
    monkeypatch.setattr(posix_worker.time, 'monotonic', lambda: next(clock))
    with pytest.raises(RuntimeError, match='handshake'):
        posix_worker.main([str(folder), 'image', '30', sys.executable, 'native-parser'])
    assert not any(name == 'exec' for name, _ in called)


def fake_transport(monkeypatch, *, exited=True):
    state = SimpleNamespace(closed=False, calls=0, code=0 if exited else None)
    raw = SimpleNamespace(pid=100, stdin=StringIO(), poll=lambda: state.code,
                          wait=lambda timeout: state.code)

    class Transport:
        def __init__(self, argv, profile, **kwargs):
            self.process = raw
            assert kwargs['memory_limit_bytes'] == budgets.MEMORY_BYTES

        def __enter__(self):
            return self

        def __exit__(self, *_):
            state.closed = True

        def next_line(self, timeout):
            state.calls += 1
            return [('stdout_closed', ''), ('stderr_closed', '')][min(state.calls, 2) - 1]
    monkeypatch.setattr(validator, 'CliProcess', Transport)
    monkeypatch.setattr(validator, 'os', SimpleNamespace(name='posix', environ=os.environ))
    return state


def test_missing_monitor_dependency_fails_before_start(tmp_path, monkeypatch):
    original = builtins.__import__

    def importing(name, *args, **kwargs):
        if name == 'image_budget':
            raise ImportError('synthetic missing psutil')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', importing)
    monkeypatch.setattr(validator, 'os', SimpleNamespace(name='posix', environ=os.environ))
    monkeypatch.setattr(validator, 'CliProcess', lambda *args, **kwargs: pytest.fail('Must not start'))
    with pytest.raises(validator.ValidatorUnavailable, match='Ressourcenmessung'):
        validator._run([sys.executable], tmp_path, resource_mode='image', timeout_seconds=30)


def test_startup_monitor_failure_closes_transport_without_parser_gate(tmp_path, monkeypatch):
    state = fake_transport(monkeypatch)
    monkeypatch.setattr(budgets, 'ImageBudget', lambda *args, **kwargs: (_ for _ in ()).throw(
        budgets.ImageBudgetError('no measurement')))
    with pytest.raises(validator.ValidatorUnavailable, match='Speicher-/Prozessbudget'):
        validator._run([sys.executable], tmp_path, resource_mode='image', timeout_seconds=30)
    assert state.closed and state.calls == 0 and not (tmp_path / budgets.READY_FILE).exists()


def test_monitor_continues_after_pipe_eof_until_process_exit(tmp_path, monkeypatch):
    state = fake_transport(monkeypatch, exited=False)
    samples = []

    class Monitor:
        def __init__(self, *args, **kwargs):
            pass

        def check(self):
            samples.append(1)
            if len(samples) == 5:
                state.code = 0

        def release(self, profile):
            self.check()

        def close(self):
            state.monitor_closed = True
    monkeypatch.setattr(budgets, 'ImageBudget', Monitor)
    assert validator._run([sys.executable], tmp_path, resource_mode='image', timeout_seconds=30) == (0, '', '')
    assert len(samples) >= 5 and state.calls >= 4 and state.closed and state.monitor_closed


@pytest.mark.parametrize('platform,mode', [('darwin', 'document'), ('linux', 'text'), ('win32', 'text')])
def test_only_darwin_text_uses_the_sampled_mode(monkeypatch, platform, mode):
    from backend.services import document_text_process
    from backend.services.document_text_reader import Budget
    monkeypatch.setattr(document_text_process.sys, 'platform', platform)
    calls = []

    def run(argv, folder, **kwargs):
        calls.append(kwargs)
        return 1, '', 'synthetic failure'
    monkeypatch.setattr(validator, '_run', run)
    part = document_text_process.read_isolated(b'synthetic', 'local.txt', {}, Budget())
    assert calls[0]['resource_mode'] == mode and calls[0]['max_processes'] == 4
    assert part.complete and part.failed and part.warning and not part.text


def test_direct_extraction_rejects_worker_failure_but_allows_successful_empty_scan(monkeypatch):
    from backend.services import document_text, document_text_process
    from backend.services.document_text_reader import ExtractionPart
    monkeypatch.setattr(validator, '_run', lambda *args, **kwargs: (1, '', 'worker failed'))
    with pytest.raises(ValueError, match='unvollständig'):
        document_text.extract(b'%PDF-synthetic', 'broken.pdf')
    monkeypatch.setattr(document_text_process, 'read_isolated',
                        lambda *args: ExtractionPart(warning='Texterkennung nicht vorhanden'))
    assert document_text.extract(b'%PDF-synthetic', 'scan.pdf') == ('', 'none')


def test_oversized_input_is_a_typed_failure_and_cannot_start_worker(monkeypatch):
    from backend.services import document_text, document_text_process
    from backend.services.document_text_reader import Budget
    monkeypatch.setattr(validator, '_run', lambda *args, **kwargs: pytest.fail('Oversized input'))
    part = document_text_process.read_isolated(b'too big', 'local.txt', {}, Budget(file_bytes=1))
    assert part.failed and part.complete and part.warning and not part.text
    monkeypatch.setattr(document_text, 'MAX_BYTES', 1)
    with pytest.raises(ValueError, match='unvollständig'):
        document_text.extract(b'too big', 'local.txt')


@pytest.mark.parametrize('failed', [False, True, 0, 1, None, 'false'])
def test_child_cannot_forge_or_coerce_parent_failure_marker(monkeypatch, failed):
    from backend.services import document_text_process
    from backend.services.document_text_reader import Budget, ExtractionPart

    def run(argv, folder, **kwargs):
        value = asdict(ExtractionPart(text='local text', source='plain'))
        value['failed'] = failed
        (folder / 'result.json').write_text(json.dumps(value), encoding='utf-8')
        return 0, '', ''
    monkeypatch.setattr(validator, '_run', run)
    part = document_text_process.read_isolated(b'local text', 'local.txt', {}, Budget())
    if failed is False:
        assert part.text == 'local text' and not part.failed and part.warning is None
    else:
        assert part.failed and not part.text and part.warning
