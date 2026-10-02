from __future__ import annotations

import io
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.ocr_service import (
    OCRLimits,
    OCRProcessingError,
    extract_pdf_text_local,
)


def _png(width=100, height=80):
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\r"
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def _tools(tmp_path, *, tesseract=True):
    names = ["pdfinfo", "pdftotext", "pdftoppm"]
    if tesseract:
        names.append("tesseract")
    result = {}
    for name in names:
        path = tmp_path / (name + ".exe")
        path.write_bytes(b"stub")
        result[name] = str(path)
    return result


def _limits(tools, **updates):
    values = dict(
        languages="deu+eng",
        pdfinfo_path=tools["pdfinfo"],
        pdftotext_path=tools["pdftotext"],
        pdftoppm_path=tools["pdftoppm"],
        tesseract_path=tools.get("tesseract", ""),
        render_dpi=200,
        max_pdf_pages=10,
        max_page_pixels=10_000_000,
        max_total_pixels=30_000_000,
        max_ram_bytes=128 * 1024 * 1024,
        max_temp_bytes=128 * 1024 * 1024,
        max_text_bytes=1024 * 1024,
        timeout_seconds=10,
    )
    values.update(updates)
    return OCRLimits(**values)


class FakeRunner:
    def __init__(self, embedded=None, ocr=None, pages=3, languages=("deu", "eng")):
        self.embedded = embedded or {}
        self.ocr = ocr or {}
        self.pages = pages
        self.languages = languages
        self.calls = []
        self.temp_parent = None

    def __call__(self, args, timeout):
        args = list(args)
        self.calls.append(args)
        tool = Path(args[0]).stem.lower()
        if tool == "pdfinfo":
            if len(args) == 2:
                return subprocess.CompletedProcess(args, 0, f"Pages: {self.pages}\n".encode(), b"")
            page = int(args[args.index("-f") + 1])
            return subprocess.CompletedProcess(
                args, 0, f"Page {page} size: 612 x 792 pts\n".encode(), b""
            )
        if tool == "pdftotext":
            page = int(args[args.index("-f") + 1])
            output = Path(args[-1])
            self.temp_parent = output.parent
            output.write_text(self.embedded.get(page, ""), encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if tool == "pdftoppm":
            page = int(args[args.index("-f") + 1])
            prefix = Path(args[-1])
            prefix.with_suffix(".png").write_bytes(_png())
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if tool == "tesseract" and "--list-langs" in args:
            body = "List of available languages:\n" + "\n".join(self.languages) + "\n"
            return subprocess.CompletedProcess(args, 0, body.encode(), b"")
        if tool == "tesseract":
            page = int(Path(args[1]).stem.rsplit("-", 1)[-1])
            Path(args[2]).with_suffix(".txt").write_text(
                self.ocr.get(page, ""), encoding="utf-8"
            )
            return subprocess.CompletedProcess(args, 0, b"", b"")
        raise AssertionError(args)


def test_explicit_high_dpi_uses_resource_budgets_without_a_product_ceiling(tmp_path):
    tools = _tools(tmp_path)
    runner = FakeRunner(pages=1, ocr={1: "Explicit high resolution"})
    result = extract_pdf_text_local(b"%PDF-1.4 synthetic", limits=_limits(tools, render_dpi=1200,
        max_page_pixels=200_000_000, max_total_pixels=200_000_000, max_ram_bytes=8_000_000_000), runner=runner)
    assert result.text == "Explicit high resolution"
    raster = next(call for call in runner.calls if Path(call[0]).stem == "pdftoppm")
    assert raster[raster.index("-r") + 1] == "1200"


def test_extreme_dpi_fails_at_correctable_pixel_budget_without_float_overflow(tmp_path):
    tools = _tools(tmp_path)
    runner = FakeRunner(pages=1)
    with pytest.raises(OCRProcessingError) as error:
        extract_pdf_text_local(b"%PDF-1.4 synthetic", limits=_limits(tools, render_dpi=10**400), runner=runner)
    assert error.value.code == "ocr_pixel_budget"
    assert not any(Path(call[0]).stem == "pdftoppm" for call in runner.calls)
    assert runner.temp_parent is not None and not runner.temp_parent.exists()


def test_mixed_pdf_preserves_text_and_ocrs_only_blank_page(tmp_path):
    tools = _tools(tmp_path)
    runner = FakeRunner(
        embedded={1: "Embedded page one", 2: "", 3: "Embedded page three"},
        ocr={2: "OCR page two"},
    )
    result = extract_pdf_text_local(
        b"%PDF-1.7\nsynthetic",
        limits=_limits(tools),
        runner=runner,
    )
    assert result.text == "Embedded page one\n\nOCR page two\n\nEmbedded page three"
    assert (result.page_count, result.embedded_text_pages, result.ocr_pages) == (3, 2, 1)
    render_calls = [call for call in runner.calls if Path(call[0]).stem == "pdftoppm"]
    assert len(render_calls) == 1 and render_calls[0][render_calls[0].index("-f") + 1] == "2"
    assert runner.temp_parent is not None and not runner.temp_parent.exists()


def test_all_embedded_text_does_not_require_tesseract(tmp_path):
    tools = _tools(tmp_path, tesseract=False)
    runner = FakeRunner(embedded={1: "one", 2: "two"}, pages=2)
    result = extract_pdf_text_local(
        b"%PDF-1.7\ntext",
        limits=_limits(tools),
        runner=runner,
    )
    assert result.text == "one\n\ntwo"
    assert result.ocr_pages == 0
    assert all(Path(call[0]).stem not in {"pdftoppm", "tesseract"} for call in runner.calls)


def test_missing_tesseract_is_explicit_for_scanned_page(tmp_path, monkeypatch):
    # Exercise absence even on a machine that provides the real OCR toolchain.
    original_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "tesseract" else original_which(name))
    tools = _tools(tmp_path, tesseract=False)
    runner = FakeRunner(embedded={1: ""}, pages=1)
    with pytest.raises(OCRProcessingError) as exc:
        extract_pdf_text_local(b"%PDF-1.7\nscan", limits=_limits(tools), runner=runner)
    assert exc.value.code == "ocr_tool_missing"
    assert "Tesseract" in exc.value.message


def test_missing_language_data_is_explicit(tmp_path):
    tools = _tools(tmp_path)
    runner = FakeRunner(embedded={1: ""}, pages=1, languages=("eng",))
    with pytest.raises(OCRProcessingError) as exc:
        extract_pdf_text_local(b"%PDF-1.7\nscan", limits=_limits(tools), runner=runner)
    assert exc.value.code == "ocr_language_missing"
    assert "deu" in exc.value.message


def test_explicit_language_directory_is_one_argument_for_probe_and_ocr(tmp_path):
    tools = _tools(tmp_path)
    data = tmp_path / "language data & local"
    data.mkdir()
    runner = FakeRunner(embedded={1: ""}, ocr={1: "synthetic"}, pages=1)
    result = extract_pdf_text_local(b"%PDF-1.7\nscan", limits=_limits(tools, tessdata_path=str(data)), runner=runner)
    assert result.text == "synthetic"
    calls = [call for call in runner.calls if Path(call[0]).stem == "tesseract"]
    assert len(calls) == 2
    assert all(call[call.index("--tessdata-dir") + 1] == str(data) for call in calls)


def test_configured_missing_language_directory_is_correctable(tmp_path):
    tools = _tools(tmp_path)
    runner = FakeRunner(embedded={1: ""}, pages=1)
    with pytest.raises(OCRProcessingError) as exc:
        extract_pdf_text_local(b"%PDF-1.7\nscan", limits=_limits(tools, tessdata_path=str(tmp_path / "missing")), runner=runner)
    assert exc.value.code == "ocr_language_missing" and exc.value.http_status == 503
    assert not any(Path(call[0]).stem == "tesseract" for call in runner.calls)


def test_timeout_aborts_and_temp_directory_is_cleaned(tmp_path):
    tools = _tools(tmp_path)
    runner = FakeRunner(embedded={1: ""}, pages=1)

    def timeout_runner(args, timeout):
        if Path(args[0]).stem == "pdftotext":
            runner.temp_parent = Path(args[-1]).parent
            raise subprocess.TimeoutExpired(args, timeout)
        return runner(args, timeout)

    with pytest.raises(OCRProcessingError) as exc:
        extract_pdf_text_local(
            b"%PDF-1.7\nscan",
            limits=_limits(tools),
            runner=timeout_runner,
        )
    assert exc.value.code == "ocr_timeout"
    assert runner.temp_parent is not None and not runner.temp_parent.exists()


def test_page_pixel_and_ram_budgets_abort_before_ocr(tmp_path):
    tools = _tools(tmp_path)

    with pytest.raises(OCRProcessingError) as page_error:
        extract_pdf_text_local(
            b"%PDF-1.7\nscan",
            limits=_limits(tools, max_pdf_pages=2),
            runner=FakeRunner(pages=3),
        )
    assert page_error.value.code == "ocr_page_budget"

    with pytest.raises(OCRProcessingError) as pixel_error:
        extract_pdf_text_local(
            b"%PDF-1.7\nscan",
            limits=_limits(tools, max_page_pixels=1_000_000),
            runner=FakeRunner(embedded={1: ""}, pages=1),
        )
    assert pixel_error.value.code == "ocr_pixel_budget"

    with pytest.raises(OCRProcessingError) as ram_error:
        extract_pdf_text_local(
            b"%PDF-1.7\nscan",
            limits=_limits(tools, max_ram_bytes=2_000_000),
            runner=FakeRunner(embedded={1: ""}, pages=1),
        )
    assert ram_error.value.code == "ocr_ram_budget"


def _real_tools():
    names = ("pdfinfo", "pdftotext", "pdftoppm", "tesseract")
    found = {name: shutil.which(name) for name in names}
    return found if all(found.values()) else None


@pytest.mark.skipif(_real_tools() is None, reason="Poppler/Tesseract not installed locally")
def test_real_local_scanned_pdf_when_tools_are_available(tmp_path):
    import reportlab
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    tools = _real_tools()
    assert tools is not None
    langs = subprocess.run(
        [tools["tesseract"], "--list-langs"],
        capture_output=True,
        check=False,
        timeout=10,
    ).stdout.decode("utf-8", errors="replace")
    if "eng" not in {line.strip() for line in langs.splitlines()}:
        pytest.skip("Tesseract eng language data not installed")

    # ReportLab ships this test font on Windows and Linux. A Windows system
    # font would silently skip the actual external-tool gate on Linux CI.
    font_path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    image = Image.new("RGB", (1400, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((60, 120), "SYNTHETIC OCR 314159", fill="black", font=ImageFont.truetype(str(font_path), 80))
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(700, 200))
    pdf.drawImage(ImageReader(image), 0, 0, width=700, height=200)
    pdf.showPage()
    pdf.save()

    result = extract_pdf_text_local(
        buffer.getvalue(),
        limits=OCRLimits(
            languages="eng",
            pdfinfo_path=tools["pdfinfo"] or "",
            pdftotext_path=tools["pdftotext"] or "",
            pdftoppm_path=tools["pdftoppm"] or "",
            tesseract_path=tools["tesseract"] or "",
            timeout_seconds=30,
        ),
    )
    assert result.ocr_pages == 1
    assert result.text and "314159" in result.text


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_native_diagnostic_overflow_is_terminated_without_unbounded_pipe(monkeypatch, stream):
    from backend.services import ocr_service

    children = []
    real_popen = subprocess.Popen

    def observed_popen(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(ocr_service.subprocess, "Popen", observed_popen)
    script = f"import sys,time; sys.{stream}.buffer.write(b'x'*500000); sys.{stream}.flush(); time.sleep(10)"
    started = time.monotonic()
    with pytest.raises(OCRProcessingError) as exc:
        ocr_service._run_command([sys.executable, "-c", script], 5)
    assert exc.value.code == "ocr_tool_output_budget"
    assert time.monotonic() - started < 5
    assert children and children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed


@pytest.mark.parametrize("kind,code", [("text", "ocr_text_budget"), ("raster", "ocr_temp_budget")])
def test_native_output_files_are_guarded_while_tool_is_running(tmp_path, kind, code):
    from backend.services.ocr_service import _CommandBudget, _run_command

    output = tmp_path / ("page.txt" if kind == "text" else "page.png")
    completed = tmp_path / "completed"
    script = (
        "import pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_bytes(b'x'*200000); "
        "time.sleep(10); pathlib.Path(sys.argv[2]).touch()"
    )
    with pytest.raises(OCRProcessingError) as exc:
        _run_command(
            [sys.executable, "-c", script, str(output), str(completed)], 5,
            budget=_CommandBudget(directory=tmp_path, text_bytes=8192, temp_bytes=32768),
        )
    assert exc.value.code == code
    assert not completed.exists()


def test_native_ram_budget_observes_real_decoder_process(tmp_path):
    import os

    from backend.services.ocr_service import _CommandBudget, _run_command

    if os.name != "nt" and not Path("/proc/self/status").exists():
        pytest.skip("Native working-set monitoring requires Windows or Linux /proc")
    completed = tmp_path / "completed"
    script = (
        "import pathlib,sys,time; allocation=bytearray(100*1024*1024); "
        "time.sleep(10); pathlib.Path(sys.argv[1]).touch()"
    )
    with pytest.raises(OCRProcessingError) as exc:
        _run_command([sys.executable, "-c", script, str(completed)], 5,
                     budget=_CommandBudget(ram_bytes=64 * 1024 * 1024))
    assert exc.value.code == "ocr_ram_budget"
    assert not completed.exists()


def test_native_timeout_reaps_process_and_closes_streams(monkeypatch):
    from backend.services import ocr_service

    children = []
    real_popen = subprocess.Popen

    def observed_popen(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(ocr_service.subprocess, "Popen", observed_popen)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        ocr_service._run_command([sys.executable, "-c", "import time; time.sleep(10)"], 0.2)
    assert time.monotonic() - started < 3
    assert children and children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed


def test_native_timeout_terminates_descendant_that_inherits_diagnostic_pipes(tmp_path):
    from backend.services.ocr_service import _run_command

    completed = tmp_path / "escaped-child-completed"
    child_script = "import pathlib,sys,time; time.sleep(10); pathlib.Path(sys.argv[1]).touch()"
    parent_script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); time.sleep(10)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_command([sys.executable, "-c", parent_script, child_script, str(completed)], 0.6)
    assert time.monotonic() - started < 3
    assert not completed.exists()


def test_invalid_executable_is_correctable_instead_of_unhandled_os_error(tmp_path):
    from backend.services.ocr_service import _run_command

    with pytest.raises(OCRProcessingError) as exc:
        _run_command([str(tmp_path / "unavailable-tool")], 1)
    assert exc.value.code == "ocr_tool_unavailable"
    assert exc.value.http_status == 503


@pytest.mark.parametrize("configured", [True, False])
def test_windows_batch_wrappers_are_rejected_before_implicit_shell(tmp_path, monkeypatch, configured):
    import os

    from backend.services.ocr_service import _resolve_tool

    if os.name != "nt":
        pytest.skip("Implicit Windows batch shell is platform specific")
    script = tmp_path / "pdfinfo.cmd"
    script.write_text("@echo implicit shell is forbidden", encoding="ascii")
    monkeypatch.setattr(shutil, "which", lambda _name: str(script))
    with pytest.raises(OCRProcessingError) as exc:
        _resolve_tool(str(script) if configured else "", "pdfinfo", "Poppler pdfinfo")
    assert exc.value.code == "ocr_config_invalid" and exc.value.http_status == 503


def test_pipe_setup_failure_reaps_already_started_native_tool(monkeypatch):
    import os

    from backend.services import ocr_service

    children = []
    real_popen = subprocess.Popen

    def observed_popen(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    def failed_setup(*args, **kwargs):
        if os.name == "nt":
            raise RuntimeError("synthetic thread capacity exhausted")
        raise OSError("synthetic descriptor capacity exhausted")

    monkeypatch.setattr(ocr_service.subprocess, "Popen", observed_popen)
    if os.name == "nt":
        monkeypatch.setattr(ocr_service.threading.Thread, "start", failed_setup)
    else:
        monkeypatch.setattr(ocr_service.selectors, "DefaultSelector", failed_setup)
    with pytest.raises(OCRProcessingError) as exc:
        ocr_service._run_command([sys.executable, "-c", "import time; time.sleep(10)"], 5)
    assert exc.value.code == "ocr_worker_unavailable" and exc.value.http_status == 503
    assert children and children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed


@pytest.mark.skipif(not Path("/proc/self/task").is_dir(), reason="Linux /proc native gate")
def test_linux_thread_created_child_memory_is_counted(tmp_path):
    import os
    import threading

    from backend.services.ocr_process_tree import ProcessTree

    children = []
    ready = tmp_path / "allocation-ready"
    child_script = "import pathlib,sys,time; data=bytearray(50*1024*1024); pathlib.Path(sys.argv[1]).touch(); time.sleep(10)"
    tree = ProcessTree(256 * 1024 * 1024)
    baseline = tree.memory(SimpleNamespace(pid=os.getpid())) or 0

    def create_from_non_main_thread():
        child = subprocess.Popen([sys.executable, "-c", child_script, str(ready)])
        children.append(child)
        child.wait()

    thread = threading.Thread(target=create_from_non_main_thread)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        # This thread's child is not listed in /proc/{pid}/task/{pid}/children.
        memory = tree.memory(SimpleNamespace(pid=os.getpid()))
        assert memory is not None and memory >= baseline + 50 * 1024 * 1024
        assert children[0].pid in tree.children if getattr(os, "pidfd_open", None) else True
    finally:
        for child in children:
            child.kill()
            child.wait()
        thread.join(timeout=3)
        # Do not kill this test runner's process group; close captured pidfds.
        for descriptor in tree.children.values():
            os.close(descriptor)
        tree.children.clear()
    assert not thread.is_alive()


@pytest.mark.skipif(not Path("/proc/self/task").is_dir(), reason="Linux /proc native gate")
def test_linux_detached_descendant_does_not_hold_cleanup_open(tmp_path):
    from backend.services.ocr_service import _run_command

    ready = tmp_path / "detached-ready"
    completed = tmp_path / "detached-completed"
    child_script = "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(10); pathlib.Path(sys.argv[2]).touch()"
    parent_script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]],start_new_session=True); "
        "time.sleep(10)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_command([sys.executable, "-c", parent_script, child_script, str(ready), str(completed)], 1)
    assert time.monotonic() - started < 3
    assert ready.exists() and not completed.exists()
    status = Path("/proc") / ready.read_text() / "stat"
    if status.exists():
        assert status.read_text().rsplit(")", 1)[1].split()[0] == "Z"  # terminated, awaiting init's reap


def test_billing_ocr_review_returns_draft_without_persisting_cost(monkeypatch):
    from backend.routers import billing
    from backend.services import file_storage, ocr_service

    class Store:
        created = False

        def get_billing_period(self, _period_id):
            return SimpleNamespace(status="draft")

        def create_cost_item(self, _payload):
            self.created = True
            raise AssertionError("OCR review must not persist costs")

    class Storage:
        def get(self, _key):
            return b"%PDF-1.7\nsynthetic"

    store = Store()
    monkeypatch.setattr(billing, "store", store)
    monkeypatch.setattr(file_storage, "get_file_storage", lambda: Storage())
    monkeypatch.setattr(
        ocr_service,
        "extract_text_from_bytes",
        lambda _data, _ext: "Lieferant: Synthetic GmbH\nGesamtbetrag: 12,34",
    )

    result = billing.import_cost_item_from_ocr(
        "period-1",
        "/uploads/documents/synthetic.pdf",
        "allocation-1",
    )

    assert result["success"] is True
    assert result["draft"]["amount"] == 12.34
    assert store.created is False
