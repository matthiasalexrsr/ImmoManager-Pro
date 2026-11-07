"""Controlled remaining transitions and ambiguous guards, not Native18 attribution."""

import base64
import errno
import hashlib
import json
import subprocess
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services import document_worker_diagnostics as diagnostics
from backend.services.e_invoice import image_budget as budgets
from backend.services.e_invoice import validator
from backend.tests import test_ai_image_budget_exit as cases

base_owned = cases.owned
KINDS = ["rss_lookup_os", "rss_lookup_psutil", "identity_not_running", "rss_not_running"]


@pytest.fixture
def subject(base_owned, monkeypatch):
    monkeypatch.setattr(budgets, "time", SimpleNamespace(monotonic=lambda: 100.0))
    base_owned[-1].deadline = 101.0
    return base_owned


def disappear(root, kind, monkeypatch):
    if kind.startswith("rss_lookup"):

        def missing():
            if kind.endswith("os"):
                raise ProcessLookupError(errno.ESRCH, "controlled own RSS lookup disappearance")
            raise budgets.psutil.NoSuchProcess(root.pid)

        monkeypatch.setattr(root, "memory_info", missing)
    elif kind == "identity_not_running":
        root.running = False
    else:
        calls = []

        def cease_on_rss_probe():
            calls.append(1)
            if len(calls) == 2:
                root.running = False

        root.on_running = cease_on_rss_probe


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("code", [0, 23])
def test_remaining_own_exit_transition_requires_bounded_kernel_completion(subject, monkeypatch, kind, code):
    root, _, raw, state, budget = subject
    disappear(root, kind, monkeypatch)
    waits = []

    def complete(*, timeout):
        assert 0 < timeout <= 0.05
        waits.append(timeout)
        state.completed, state.reaped, state.returncode = True, True, code
        root.created = 99
        return code

    monkeypatch.setattr(raw, "wait", complete)
    budget.check()
    assert len(waits) == 1 and raw.poll() == code and root.pid not in budget.known
    budget.close()
    assert not root.killed


@pytest.mark.parametrize("kind", KINDS)
def test_root_confirmation_still_checks_live_descendant_after_wait(subject, monkeypatch, kind):
    root, processes, raw, state, budget = subject
    child = cases.Owned(101)
    child.created = 11
    processes[101] = child
    root.descendants = [child]
    budget.check()
    disappear(root, kind, monkeypatch)

    def complete(*, timeout):
        state.completed, state.reaped = True, True
        child.rss = budgets.MEMORY_BYTES + 1
        return 0

    monkeypatch.setattr(raw, "wait", complete)
    with pytest.raises(budgets.ImageBudgetError, match="exceeds"):
        budget.check()
    budget.close()
    assert child.killed and not root.killed


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("failure", ["timeout", "permission", "no_deadline"])
def test_noncompleted_or_denied_root_is_never_accepted(subject, monkeypatch, kind, failure):
    root, _, raw, state, budget = subject
    disappear(root, kind, monkeypatch)
    if failure == "no_deadline":
        budget.deadline = None

    def unfinished(*, timeout):
        assert 0 < timeout <= 0.05
        if failure == "no_deadline":
            pytest.fail("Missing deadline must never add wait")
        if failure == "permission":
            raise PermissionError(errno.EPERM, "controlled wait denial")
        raise subprocess.TimeoutExpired("controlled-own-child", timeout)

    monkeypatch.setattr(raw, "wait", unfinished)
    with pytest.raises(budgets.ImageBudgetError):
        budget.check()
    assert not state.completed and not state.reaped


@pytest.mark.parametrize(
    "guard,expected_stage",
    [
        ("root_missing", "budget_root_measurement_lost"),
        ("identity", "budget_root_identity"),
        ("limits", "budget_limits"),
    ],
)
def test_three_distinct_guards_need_content_free_distinct_observation(
    subject, monkeypatch, caplog, guard, expected_stage
):
    root, _, _, _, budget = subject
    if guard == "root_missing":
        disappear(root, "rss_lookup_os", monkeypatch)
        budget.deadline = None
    elif guard == "identity":
        root.created = 99
    else:
        root.rss = budgets.MEMORY_BYTES + 1

    @diagnostics.observed_run
    def attempt(**kwargs):
        diagnostics.stage("rss_probe")
        try:
            try:
                budget.check()
            except budgets.ImageBudgetError:
                raise validator.ValidatorUnavailable("controlled generic public category") from None
        finally:
            raise PermissionError("controlled secondary cleanup; never log this text")

    with pytest.raises(PermissionError):
        attempt(resource_mode="image")
    prefix = "IMMO_DOCUMENT_WORKER_FAILURE "
    rows = [
        json.loads(record.getMessage().split(prefix, 1)[1])
        for record in caplog.records
        if prefix in record.getMessage()
    ]
    assert len(rows) == 1
    assert rows[0]["error_types"][:3] == ["PermissionError", "ValidatorUnavailable", "ImageBudgetError"]
    assert rows[0]["stage"] == expected_stage
    assert "controlled" not in caplog.text


@pytest.mark.parametrize(
    "guard",
    [
        "budget_configuration",
        "budget_initial_owner",
        "budget_initial_measurement",
        "budget_root_identity",
        "budget_descendant_identity",
        "budget_descendant_changed",
        "budget_descendant_escape",
        "budget_root_unmeasurable",
        "budget_root_lookup_unconfirmed",
        "budget_owned_identity",
        "budget_invalid_rss",
        "budget_root_measurement_lost",
        "budget_limits",
        "budget_measurement_error",
        "budget_exit_unconfirmed",
    ],
)
def test_every_explicit_guard_publishes_only_its_fixed_category(subject, monkeypatch, caplog, guard):
    root, processes, raw, state, budget = subject
    action = budget.check
    child = cases.Owned(101)
    child.created = 11

    def construct():
        budgets.ImageBudget(raw, max_processes=0 if guard == "budget_configuration" else 2)

    if guard == "budget_configuration":
        action = construct
    elif guard == "budget_initial_owner":
        root.group = 999
        action = construct
    elif guard == "budget_initial_measurement":
        monkeypatch.setattr(root, "create_time", lambda: (_ for _ in ()).throw(budgets.psutil.AccessDenied(root.pid)))
        action = construct
    elif guard == "budget_root_identity":
        root.created = 99
    elif guard.startswith("budget_descendant"):
        processes[101] = child
        root.descendants = [child]
        if guard == "budget_descendant_identity":
            child.created = 9
        elif guard == "budget_descendant_changed":
            budget.check()
            child.created = 12
        else:
            child.group = 999
    elif guard == "budget_root_unmeasurable":
        root.running, budget.deadline = False, None
    elif guard in {"budget_root_lookup_unconfirmed", "budget_exit_unconfirmed"}:
        state.group_failure = ProcessLookupError(errno.ESRCH, "controlled missing root")
        if guard == "budget_root_lookup_unconfirmed":
            budget.deadline = None
        else:
            monkeypatch.setattr(
                raw, "wait", lambda **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("controlled", 0.05))
            )
    elif guard == "budget_owned_identity":
        calls = []

        def change_before_rss():
            calls.append(1)
            if len(calls) == 2:
                root.created = 99

        root.on_running = change_before_rss
    elif guard == "budget_invalid_rss":
        root.rss = True
    elif guard == "budget_root_measurement_lost":
        disappear(root, "rss_lookup_os", monkeypatch)
        budget.deadline = None
    elif guard == "budget_limits":
        root.rss = budgets.MEMORY_BYTES + 1
    else:
        monkeypatch.setattr(root, "memory_info", lambda: (_ for _ in ()).throw(budgets.psutil.AccessDenied(root.pid)))
    with pytest.raises(budgets.ImageBudgetError):
        with diagnostics.observation("image"):
            action()
    prefix = "IMMO_DOCUMENT_WORKER_FAILURE "
    rows = [
        json.loads(record.getMessage().split(prefix, 1)[1])
        for record in caplog.records
        if prefix in record.getMessage()
    ]
    assert len(rows) == 1 and rows[0]["stage"] == guard and guard in diagnostics.STAGES
    assert set(rows[0]) == {"schema", "mode", "stage", "error_types", "exit_code", "duration_ms", "child"}
    assert "controlled" not in caplog.text and rows[0]["child"] is None


@pytest.fixture
def repeat_case(tmp_path, monkeypatch):
    from PIL import Image

    from backend.services import ai_document_images
    from scripts import check_desktop_runtime as smoke

    pictures = {}
    for mime, dimensions in (("image/png", (8, 4)), ("application/pdf", (300, 150))):
        stream = BytesIO()
        Image.new("RGB", dimensions, (20, 110, 100)).save(stream, "PNG")
        pictures[mime] = stream.getvalue()
    inputs = {"image/png": pictures["image/png"], "application/pdf": b"%PDF-synthetic-repeat-driver-only"}
    reference: dict[str, Any] = {"packaged_runtime": False, "cases": {}}
    for mime, name, expected_pixels in (
        ("image/png", "ai-worker-smoke.png", [8, 4]),
        ("application/pdf", "ai-worker-smoke.pdf", [300, 150]),
    ):
        (tmp_path / name).write_bytes(inputs[mime])
        reference["cases"][mime] = {
            "status": "rendered",
            "input_sha256": hashlib.sha256(inputs[mime]).hexdigest(),
            "image_sha256": hashlib.sha256(pictures[mime]).hexdigest(),
            "image_bytes": len(pictures[mime]),
            "pixels": expected_pixels,
        }
    baseline = tmp_path / "ai-image-worker-smoke.json"
    baseline.write_bytes(b'{"original_success_schema_unchanged":true}\n')
    mode = SimpleNamespace(fault=None, at=1)
    calls, processes = [], []
    shared = SimpleNamespace(poll=lambda: 0)

    def factory(*args, **kwargs):
        assert args == (["controlled-worker"], tmp_path)
        assert kwargs == {
            "memory_limit_bytes": budgets.MEMORY_BYTES,
            "max_processes": 2,
            "env": {"PRIVATE": "controlled"},
        }
        process = (
            shared if mode.fault == "reused" else SimpleNamespace(poll=lambda: 23 if mode.fault == "nonzero" else 0)
        )
        processes.append(process)
        return SimpleNamespace(process=process)

    monkeypatch.setattr(validator, "CliProcess", factory)

    def render(content, mime, name, max_pages):
        calls.append(mime)
        assert content == inputs[mime] and max_pages == 1
        fault = mode.fault if len(calls) == mode.at else None
        if fault != "cached":
            validator.CliProcess(
                ["controlled-worker"],
                tmp_path,
                memory_limit_bytes=budgets.MEMORY_BYTES,
                max_processes=2,
                env={"PRIVATE": "controlled"},
            )
        if fault == "worker_error":
            raise RuntimeError("controlled worker failure")
        image = {"mime": "image/png", "data_base64": base64.b64encode(pictures[mime]).decode("ascii")}
        value = {"pages_total": 1, "pages_sent": 1, "images": [image], "omissions": []}
        if fault == "bad_hash":
            image["data_base64"] = base64.b64encode(pictures[mime] + b"changed").decode("ascii")
        elif fault == "bad_pixels":
            wrong = bytearray(pictures[mime])
            wrong[16:20] = (999).to_bytes(4, "big")
            image["data_base64"] = base64.b64encode(wrong).decode("ascii")
        elif fault == "omission":
            value["omissions"] = ["controlled"]
        elif fault == "source_changed":
            (tmp_path / name).write_bytes(b"changed")
        return value

    monkeypatch.setattr(ai_document_images, "render_page_images", render)
    return smoke, reference, mode, calls, processes, baseline


def test_source_repeat_driver_requires_six_distinct_terminated_workers_and_same_host_bytes(repeat_case, tmp_path):
    smoke, reference, _, calls, processes, baseline = repeat_case
    original = baseline.read_bytes()
    result = smoke.verify_ai_image_worker_repeats(tmp_path, reference)
    assert result["status"] == "passed" and result["pairs_completed"] == 3
    assert calls == ["image/png", "application/pdf"] * 3 and len(processes) == 6
    assert (
        result["worker_starts"]
        == result["terminated_workers"]
        == result["zero_exit_workers"]
        == result["unique_workers"]
        == 6
    )
    assert len(result["cases"]) == 6 and baseline.read_bytes() == original


@pytest.mark.parametrize(
    "fault,at,expected_calls",
    [
        ("cached", 1, 1),
        ("reused", 1, 2),
        ("nonzero", 1, 1),
        ("worker_error", 3, 3),
        ("bad_hash", 1, 1),
        ("bad_pixels", 1, 1),
        ("omission", 1, 1),
        ("source_changed", 1, 1),
    ],
)
def test_repeat_driver_stops_on_first_failed_case_without_retry_or_old_success_mutation(
    repeat_case, tmp_path, fault, at, expected_calls
):
    smoke, reference, mode, calls, _, baseline = repeat_case
    original = baseline.read_bytes()
    mode.fault, mode.at = fault, at
    with pytest.raises((AssertionError, RuntimeError)):
        smoke.verify_ai_image_worker_repeats(tmp_path, reference)
    observed = json.loads((tmp_path / "ai-image-worker-repeat-smoke.json").read_text())
    assert observed["status"] == "failed" and len(calls) == expected_calls
    assert observed["pairs_completed"] < 3 and baseline.read_bytes() == original


@pytest.mark.parametrize("invalid", ["frozen", "reference_digest"])
def test_repeat_driver_rejects_packaged_or_stale_reference_before_any_worker(
    repeat_case, tmp_path, monkeypatch, invalid
):
    smoke, reference, _, calls, _, _ = repeat_case
    if invalid == "frozen":
        monkeypatch.setattr(smoke, "sys", SimpleNamespace(frozen=True))
    else:
        reference["cases"]["image/png"]["input_sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        smoke.verify_ai_image_worker_repeats(tmp_path, reference)
    assert calls == []
    assert json.loads((tmp_path / "ai-image-worker-repeat-smoke.json").read_text())["status"] == "failed"
