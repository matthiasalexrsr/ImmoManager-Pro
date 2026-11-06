"""Bounded synthetic BW HTTP/queue/restart stress; never attach to an existing server.

Run with the application's Python: python scripts/release_stress.py --output NEW_DIR
The output contains private synthetic profiles. Share report.json/report.md, not profiles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def percentiles(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {"count": len(values), "p50_ms": round(ordered[math.ceil(len(values) * .5) - 1] * 1000, 3),
            "p95_ms": round(ordered[math.ceil(len(values) * .95) - 1] * 1000, 3),
            "max_ms": round(ordered[-1] * 1000, 3)}


def wait_port_closed(port, timeout=3, *, probe=None, clock=time.monotonic, sleep=time.sleep):
    def connect():
        with socket.socket() as connection:
            connection.settimeout(.2)
            return connection.connect_ex(("127.0.0.1", port)) != 0
    probe = probe or connect
    deadline = clock() + timeout
    while True:
        if probe():
            return True
        if clock() >= deadline:
            return False
        sleep(.02)


def snapshot():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    names = sorted(set(tracked + untracked) - {""})
    hashes = {}
    for name in names:
        path = ROOT / name
        if path.is_symlink():
            hashes[name] = hashlib.sha256(os.readlink(path).encode()).hexdigest()
        elif path.is_file():
            with path.open("rb") as stream:
                hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        else:
            hashes[name] = None
    changes = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    return {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "base_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
            "working_changes": changes, "clean": not changes, "files": hashes}


def source_eligible(before, after, workload_passed):
    return bool(workload_passed and before.get("clean") is True and after.get("clean") is True
                and before == after)


def serve(data, port):
    """Only called in a newly owned child with a marker and private environment."""
    if port is None or not 1024 <= port <= 65535 or port == 8765:
        raise RuntimeError("Internal fixture requires a nonprivileged port other than the live application port")
    marker = data.parent / ".release-stress-owned.json"
    if not marker.is_file() or data.parent != Path(os.environ["RELEASE_STRESS_OUTPUT"]).resolve():
        raise RuntimeError("Refusing an unowned fixture")
    from backend.demo import configure_environment
    configure_environment(data)
    # Explicit fault injection exists only in this marked synthetic server.
    # It changes latency/outcome, never selects an external provider.
    from backend.services import assistant_providers
    from backend.services.assistant_provider_protocol import ProviderError
    original_answer = assistant_providers._local_answer

    def controlled_answer(request):
        content = str((request.get("messages") or [{}])[-1].get("content", ""))
        if content.startswith(("[STRESS-HOLD]", "[STRESS-UNKNOWN]")):
            with (data / "fault-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"run_id": request.get("run_id"), "unknown": content.startswith("[STRESS-UNKNOWN]")})+"\n")
            if content.startswith("[STRESS-UNKNOWN]"):
                raise ProviderError("Synthetic uncertain outcome", "stress_injected", uncertain=True)
            time.sleep(1)
        return original_answer(request)
    assistant_providers._local_answer = controlled_answer
    import uvicorn
    server = uvicorn.Server(uvicorn.Config("backend.app:app", host="127.0.0.1", port=port,
                                         log_level="warning", access_log=False))

    def control():
        token = os.environ.pop("RELEASE_STRESS_TOKEN")
        for line in sys.stdin:
            if line.strip() == "STOP " + token:
                break
        server.should_exit = True
    threading.Thread(target=control, daemon=True).start()
    server.run()


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows, self.findings = [], []
        self.active, self.max_active = 0, 0

    def record(self, phase, status, elapsed, expected, detail=""):
        with self.lock:
            self.rows.append({"phase": phase, "status": status, "seconds": elapsed,
                              "expected": expected, "detail": detail[:300]})
            if not expected:
                self.findings.append({"phase": phase, "status": status, "detail": detail[:300]})

    def check(self, condition, label, detail=""):
        self.record(label, "oracle", 0, bool(condition), detail if not condition else "")
        return condition

    def summary(self):
        groups = defaultdict(list)
        for row in self.rows:
            groups[row["phase"]].append(row)
        return {name: {**percentiles([r["seconds"] for r in rows]),
                       "statuses": dict(Counter(str(r["status"]) for r in rows)),
                       "unexpected": sum(not r["expected"] for r in rows),
                       "unexpected_rate": sum(not r["expected"] for r in rows)/len(rows)} for name, rows in groups.items()}


class Fixture:
    def __init__(self, output, args, metrics):
        from tools.xstress.core import free_port
        self.output, self.data, self.args, self.metrics = output, output / "profile", args, metrics
        self.port, self.token = free_port(), secrets.token_urlsafe(32)
        if self.port == 8765:
            raise RuntimeError("Reserved live application port")
        self.proc = self.job = None
        self.lock, self.stop_monitor, self.limit_hit = threading.RLock(), threading.Event(), threading.Event()
        self.shutdowns, self.samples = [], []
        self.started, self.boots = time.monotonic(), 0
        self.cpu_seen, self.cpu_total = {}, 0.0
        self.monitor_error = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        import httpx

        from scripts.check_frozen_desktop import isolated_environment
        from tools.xstress.processes import start_owned
        with self.lock:
            if self.proc is not None:
                raise RuntimeError("Owned process must be closed before restart")
            self.boots += 1
            folder = self.output / ("boot-" + str(self.boots))
            folder.mkdir()
            environment = isolated_environment(folder, self.port)
            environment.update(PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", RELEASE_STRESS_OUTPUT=str(self.output),
                               RELEASE_STRESS_TOKEN=self.token, RATE_LIMIT_ENABLED="false")
            with (folder / "server.log").open("w", encoding="utf-8") as log:
                self.proc, self.job = start_owned([sys.executable, str(Path(__file__).resolve()), "--serve",
                    "--profile", str(self.data), "--port", str(self.port)], cwd=ROOT, env=environment,
                    stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        deadline = time.monotonic() + self.args.startup_timeout
        with httpx.Client(trust_env=False, timeout=2) as client:
            while time.monotonic() < deadline:
                self.guard()
                if self.proc.poll() is not None:
                    raise RuntimeError("Own server exited during startup")
                try:
                    response = client.get(self.url + "/health")
                    health = response.json()
                    if response.status_code == 200 and health.get("demo_ready") is True:
                        return health
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(.1)
        raise TimeoutError("Own demo startup timed out")

    def stop(self, hard=False):
        from tools.xstress.processes import stop_owned
        with self.lock:
            if self.proc is None:
                return
            proc, job = self.proc, self.job
            if not hard and proc.poll() is None:
                proc.stdin.write("STOP " + self.token + "\n")
                proc.stdin.flush()
                proc.stdin.close()
                proc.wait(timeout=30)
            stop_owned(proc, job, hard=hard)
            closed = wait_port_closed(self.port)
            self.shutdowns.append({"boot": self.boots, "hard_crash_requested": hard,
                                   "exit_code": proc.returncode, "port_closed": closed})
            self.proc = self.job = None
            self.metrics.check(closed and (hard or proc.returncode == 0), "owned_process_cleanup")

    def guard(self):
        if self.limit_hit.is_set():
            raise RuntimeError("Own resource/wall budget exceeded")
        if time.monotonic() - self.started > self.args.max_seconds:
            self.limit_hit.set()
            raise TimeoutError("Stress wall budget exceeded")

    def monitor(self):
        import psutil
        while not self.stop_monitor.wait(.25):
            with self.lock:
                proc = self.proc
                if proc is None:
                    continue
                try:
                    # Include the load generator itself, not only the server.
                    # This process owns every descendant started by this harness.
                    parent = psutil.Process(os.getpid())
                    processes = [parent, *parent.children(recursive=True)]
                    rss = 0
                    for child in processes:
                        try:
                            identity = (child.pid, child.create_time())
                            rss += child.memory_info().rss
                            times = child.cpu_times()
                            cpu = times.user + times.system
                            self.cpu_total += max(0, cpu - self.cpu_seen.get(identity, 0))
                            self.cpu_seen[identity] = cpu
                        except psutil.NoSuchProcess:
                            continue
                    disk = sum(p.stat().st_size for p in self.output.rglob("*") if p.is_file())
                    self.samples.append({"seconds": round(time.monotonic()-self.started, 3), "rss_bytes": rss,
                        "cpu_seconds": round(self.cpu_total, 3), "disk_bytes": disk})
                    if (rss > self.args.max_rss_mb * 1024**2 or disk > self.args.max_disk_mb * 1024**2
                            or self.cpu_total > self.args.max_cpu_seconds
                            or time.monotonic()-self.started > self.args.max_seconds):
                        self.limit_hit.set()
                        self.stop(hard=True)
                except (psutil.NoSuchProcess, FileNotFoundError):
                    continue
                except (psutil.Error, OSError) as error:
                    self.monitor_error = type(error).__name__
                    self.limit_hit.set()
                    self.stop(hard=True)
                    return


def request(fixture, metrics, client, method, path, *, actor=None, body=None, expected=(200,), phase="http", files=None, raw=False):
    import httpx
    fixture.guard()
    started = time.perf_counter()
    with metrics.lock:
        metrics.active += 1
        metrics.max_active = max(metrics.max_active, metrics.active)
    try:
        response = client.request(method, fixture.url + path,
            headers={"Authorization": "Bearer " + actor} if actor else {}, json=body, files=files)
        metrics.record(phase, response.status_code, time.perf_counter()-started, response.status_code in expected,
                       response.text[:300] if response.status_code not in expected else "")
        if raw:
            return response.status_code, response.content
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}
    except httpx.HTTPError as error:
        metrics.record(phase, type(error).__name__, time.perf_counter()-started, False, str(error))
        return 0, {}
    finally:
        with metrics.lock:
            metrics.active -= 1


def inventory(data):
    from backend.services.sqlite_backup import readonly_uri
    from scripts.check_demo_runtime import inspect_demo
    marker, counts = inspect_demo(data)
    with sqlite3.connect(readonly_uri(data / "demo-bw.sqlite3"), uri=True) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
    return {"identity": marker["identity"], "counts": counts, "integrity_check": result}


def wait_run(fixture, metrics, client, actor, run):
    deadline = time.monotonic() + 25
    while run.get("state") in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(.05)
        _, run = request(fixture, metrics, client, "GET", "/api/v1/assistant/runs/" + run["id"],
                         actor=actor, phase="queue_poll")
    return run


def attachment_corpus(fixture, metrics, client, owner):
    from docx import Document
    from PIL import Image
    from reportlab.pdfgen.canvas import Canvas
    text = "Hausservice Neckar GmbH\nRechnung BW-2026-4711\nDatum 06.11.2026\nNetto 100,00 EUR\nUmsatzsteuer 19 % 19,00 EUR\nBrutto 119,00 EUR\nBaden-Wuerttemberg ORIGINAL-4711"
    pdf = BytesIO()
    canvas = Canvas(pdf, invariant=1)
    for number, line in enumerate(text.splitlines()):
        canvas.drawString(50, 800-number*18, line)
    canvas.save()
    word = Document()
    word.add_paragraph("BW Haupttext ORIGINAL-BODY")
    word.add_table(rows=1, cols=1).cell(0, 0).text = "ORIGINAL-TABLE"
    word.sections[0].header.paragraphs[0].text = "ORIGINAL-HEADER"
    word.sections[0].footer.paragraphs[0].text = "ORIGINAL-FOOTER"
    docx = BytesIO()
    word.save(docx)
    png = BytesIO()
    Image.new("RGB", (32, 16), "green").save(png, "PNG")
    cases = [("invoice.txt", text.encode(), ["ORIGINAL-4711", "119,00"], False),
             ("invoice.pdf", pdf.getvalue(), ["ORIGINAL-4711", "119,00"], False),
             ("document.docx", docx.getvalue(), ["ORIGINAL-BODY", "ORIGINAL-TABLE", "ORIGINAL-HEADER", "ORIGINAL-FOOTER"], False),
             ("picture.png", png.getvalue(), ["lokal keine automatische OCR"], False),
             ("long.txt", ("BW-LANGDOKUMENT "*70000).encode(), ["BW-LANGDOKUMENT"], True)]
    records = []
    for name, content, phrases, truncated in cases:
        _, chat = request(fixture, metrics, client, "POST", "/api/v1/assistant/conversations", actor=owner,
            body={"idempotency_key": str(uuid4()), "title": "Dateikorpus "+name, "provider": "local", "data_scope": "none"}, phase="corpus_chat")
        _, attachment = request(fixture, metrics, client, "POST", f'/api/v1/assistant/conversations/{chat["id"]}/attachments',
            actor=owner, files={"file": (name, content)}, phase="corpus_upload")
        digest = hashlib.sha256(content).hexdigest()
        metrics.check(attachment.get("sha256")==digest and attachment.get("text_truncated") is truncated, "attachment_hash_and_limit", name)
        _, returned = request(fixture, metrics, client, "GET", "/api/v1/assistant/attachments/"+attachment["id"]+"/download",
                              actor=owner, raw=True, phase="corpus_download")
        metrics.check(hashlib.sha256(returned).hexdigest()==digest, "attachment_original_unchanged", name)
        _, current = request(fixture, metrics, client, "GET", "/api/v1/assistant/conversations/"+chat["id"], actor=owner)
        _, run = request(fixture, metrics, client, "POST", f'/api/v1/assistant/conversations/{chat["id"]}/runs', actor=owner,
            body={"idempotency_key":str(uuid4()),"expected_revision":current["revision"],"content":"Datei lokal pruefen",
                  "data_scope":"none","attachment_ids":[attachment["id"]]},phase="corpus_submit")
        run = wait_run(fixture, metrics, client, owner, run)
        passed = run.get("state")=="completed" and all(phrase in run.get("response", "") for phrase in phrases)
        metrics.check(passed, "real_parser_queue_corpus", name)
        records.append({"name":name,"bytes":len(content),"sha256":digest,"expected_phrases":phrases,
                        "truncation_expected":truncated,"passed":passed,"run_state":run.get("state")})
    for name, content, expected in [("broken.pdf",b"%PDF-broken",422),("broken.png",b"not image",415),
                                     ("binary.txt",b"text\x00binary",415),("empty.txt",b"",413)]:
        status, _ = request(fixture, metrics, client,"POST",f'/api/v1/assistant/conversations/{chat["id"]}/attachments',
            actor=owner,files={"file":(name,content)},expected=(expected,),phase="invalid_document_refused")
        records.append({"name":name,"bytes":len(content),"expected_status":expected,"actual_status":status})
    return records


def queue_fault_contracts(fixture, metrics, owner, prop):
    import httpx
    records = []
    with httpx.Client(trust_env=False, timeout=10) as client:
        command = {"idempotency_key":str(uuid4()),"title":"Paralleler Doppelklick","provider":"local","data_scope":"none"}
        def duplicate(_):
            with httpx.Client(trust_env=False, timeout=10) as parallel:
                return request(fixture,metrics,parallel,"POST","/api/v1/assistant/conversations",actor=owner,
                               body=command,expected=(200,409),phase="simultaneous_idempotency")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(duplicate,range(4)))
        _, replay=request(fixture,metrics,client,"POST","/api/v1/assistant/conversations",actor=owner,body=command)
        identifiers={r["id"] for status,r in results if status==200}
        metrics.check(identifiers=={replay["id"]},"simultaneous_create_single_identity")

        def submit(title,content,selection):
            _,chat=request(fixture,metrics,client,"POST","/api/v1/assistant/conversations",actor=owner,
                body={"idempotency_key":str(uuid4()),"title":title,"provider":"local","data_scope":"selected"})
            body={"idempotency_key":str(uuid4()),"expected_revision":chat["revision"],"content":content,
                  "data_scope":"selected","context":selection}
            _,run=request(fixture,metrics,client,"POST",f'/api/v1/assistant/conversations/{chat["id"]}/runs',
                          actor=owner,body=body,phase="fault_submit")
            return chat,run,body

        def current_run(run):
            return request(fixture,metrics,client,"GET","/api/v1/assistant/runs/"+run["id"],actor=owner)[1]

        chat,run,_=submit("Abbruch unter Last","[STRESS-HOLD] Quellen pruefen",{"property_ids":[prop["id"]]})
        deadline=time.monotonic()+5
        while run["state"]=="queued" and time.monotonic()<deadline:
            time.sleep(.02)
            run=current_run(run)
        metrics.check(run["state"]=="running","cancel_saw_running")
        cancel={"idempotency_key":str(uuid4()),"expected_revision":run["revision"]}
        _,cancelled=request(fixture,metrics,client,"POST",f'/api/v1/assistant/runs/{run["id"]}/cancel',
                            actor=owner,body=cancel,phase="running_cancel")
        metrics.check(cancelled.get("state")=="cancelled","cancel_response")
        request(fixture,metrics,client,"POST",f'/api/v1/assistant/runs/{run["id"]}/cancel',actor=owner,body=cancel,phase="cancel_replay")
        time.sleep(1.2)
        late=current_run(run)
        metrics.check(late["state"]=="cancelled" and not late.get("response"),"late_answer_cannot_overwrite_cancel")
        _,current=request(fixture,metrics,client,"GET","/api/v1/assistant/conversations/"+chat["id"],actor=owner)
        _,narrowed=request(fixture,metrics,client,"PATCH","/api/v1/assistant/conversations/"+chat["id"],actor=owner,
            body={"idempotency_key":str(uuid4()),"expected_revision":current["revision"],"data_scope":"none"},phase="narrow_grant")
        request(fixture,metrics,client,"POST",f'/api/v1/assistant/runs/{run["id"]}/retry',actor=owner,
                body={"idempotency_key":str(uuid4()),"expected_revision":late["revision"]},expected=(409,),phase="retry_after_narrower_grant")
        request(fixture,metrics,client,"PATCH","/api/v1/assistant/conversations/"+chat["id"],actor=owner,
            body={"idempotency_key":str(uuid4()),"expected_revision":current["revision"],"title":"stale update"},
            expected=(409,),phase="stale_revision_refused")
        metrics.check(narrowed.get("data_scope")=="none","narrow_grant_persisted")
        records.append({"case":"cancel_and_narrow_retry","run_id":run["id"],"state":late["state"]})

        chat,run,body=submit("Unklarer Ausgang","[STRESS-UNKNOWN] Test",{})
        unknown=wait_run(fixture,metrics,client,owner,run)
        _,replay=request(fixture,metrics,client,"POST",f'/api/v1/assistant/conversations/{chat["id"]}/runs',
                         actor=owner,body=body,phase="unknown_idempotency_replay")
        metrics.check(unknown["state"]=="unknown" and replay["id"]==unknown["id"],"unknown_not_completed_or_resubmitted")
        time.sleep(.3)
        events=[json.loads(line) for line in (fixture.data/"fault-events.jsonl").read_text(encoding="utf-8").splitlines()]
        metrics.check(sum(e["run_id"]==run["id"] for e in events)==1,"unknown_never_automatically_repeated")
        records.append({"case":"uncertain_outcome","run_id":run["id"],"state":unknown["state"]})

        _,run,_=submit("Geaenderte Quelle","[STRESS-HOLD] Akte pruefen",{"property_ids":[prop["id"]]})
        deadline=time.monotonic()+5
        while run["state"]=="queued" and time.monotonic()<deadline:
            time.sleep(.02)
            run=current_run(run)
        request(fixture,metrics,client,"PATCH","/api/v1/properties/"+prop["id"],actor=owner,
                body={"name":prop["name"]+" [Stressstand]"},phase="source_changes_while_running")
        stale=wait_run(fixture,metrics,client,owner,run)
        metrics.check(stale.get("verification_status")=="stale" and stale.get("state")=="completed", "changed_source_is_marked_stale")
        request(fixture,metrics,client,"PATCH","/api/v1/properties/"+prop["id"],actor=owner,body={"name":prop["name"]})
        records.append({"case":"source_changed_during_run","run_id":run["id"],"state":stale["state"],"verification_status":stale.get("verification_status")})
    return records


def exercise(fixture, metrics):
    import httpx
    actors, acknowledged, lock = [], {}, threading.Lock()
    with httpx.Client(trust_env=False, timeout=10) as client:
        _, login = request(fixture, metrics, client, "POST", "/api/v1/auth/login",
                           body={"username": "demo.bw", "password": "Immo-Demo-BW-2026!"}, phase="login")
        owner = login["access_token"]
        _, properties = request(fixture, metrics, client, "GET", "/api/v1/properties?limit=1000", actor=owner)
        _, portfolios = request(fixture, metrics, client, "GET", "/api/v1/portfolios?limit=1000", actor=owner)
        prop = properties[0]
        for index in range(fixture.args.workers):
            username = f"stress-user-{index}"
            request(fixture, metrics, client, "POST", "/api/v1/auth/users", actor=owner, expected=(201,),
                    body={"username": username, "password": "Stress-Test-2026!", "email": username+"@example.invalid",
                          "full_name": "Synthetischer Stresstest " + str(index), "role": "verwalter",
                          "portfolio_access": "selected", "portfolio_ids": [p["id"] for p in portfolios]}, phase="users")
            _, result = request(fixture, metrics, client, "POST", "/api/v1/auth/login",
                    body={"username": username, "password": "Stress-Test-2026!"}, phase="login")
            actors.append(result["access_token"])
    baseline = inventory(fixture.data)

    def worker(index, count, phase):
        with httpx.Client(trust_env=False, timeout=10) as client:
            actor = actors[index % len(actors)]
            for offset in range(count):
                if fixture.limit_hit.is_set():
                    break
                if phase == "scale" or offset % 4 == 0:
                    title = f"BW-Stress {phase} {index}-{offset}"
                    status, result = request(fixture, metrics, client, "POST", "/api/v1/tasks", actor=actor,
                        body={"title": title, "description": "Eigene synthetische BW-Testdaten", "property_id": prop["id"]},
                        expected=(201,), phase=phase+"_write")
                    if status == 201:
                        with lock:
                            acknowledged[result["id"]] = title
                else:
                    path = ["/api/v1/tasks?limit=1000", "/api/v1/bookings?limit=100", "/api/v1/properties?limit=1000"][offset % 3]
                    request(fixture, metrics, client, "GET", path, actor=actor, phase=phase+"_read")

    with ThreadPoolExecutor(max_workers=fixture.args.workers) as pool:
        list(pool.map(lambda i: worker(i, fixture.args.scale_tasks // fixture.args.workers, "scale"), range(fixture.args.workers)))
        list(pool.map(lambda i: worker(i, fixture.args.operations // fixture.args.workers, "mixed"), range(fixture.args.workers)))
    # Real local queue and strict replay/stale/ownership commands; no model client.
    queue_records = []
    with httpx.Client(trust_env=False, timeout=15) as client:
        for index in range(fixture.args.assistant_runs):
            command = {"idempotency_key": str(uuid4()), "title": "BW Queue " + str(index), "provider": "local", "data_scope": "none"}
            _, chat = request(fixture, metrics, client, "POST", "/api/v1/assistant/conversations", actor=owner, body=command, phase="queue_create")
            _, replay = request(fixture, metrics, client, "POST", "/api/v1/assistant/conversations", actor=owner, body=command, phase="queue_replay")
            metrics.check(chat.get("id") == replay.get("id"), "chat_idempotency")
            request(fixture, metrics, client, "GET", "/api/v1/assistant/conversations/"+chat["id"], actor=actors[0], expected=(404,), phase="cross_owner")
            run_command = {"idempotency_key": str(uuid4()), "expected_revision": chat["revision"], "content": "Lokal prüfen", "data_scope": "none"}
            _, run = request(fixture, metrics, client, "POST", f'/api/v1/assistant/conversations/{chat["id"]}/runs', actor=owner, body=run_command, phase="queue_submit")
            _, replay_run = request(fixture, metrics, client, "POST", f'/api/v1/assistant/conversations/{chat["id"]}/runs', actor=owner, body=run_command, phase="queue_replay")
            metrics.check(run.get("id") == replay_run.get("id"), "run_idempotency")
            run = wait_run(fixture, metrics, client, owner, run)
            metrics.check(run.get("state")=="completed" and run.get("provider")=="local" and "Lokale Analyse" in run.get("response", ""), "local_queue_oracle", str(run.get("state")))
            queue_records.append({"id":run["id"], "state":run.get("state")})
        corpus = attachment_corpus(fixture, metrics, client, owner)
    fault_contracts = queue_fault_contracts(fixture, metrics, owner, prop)
    # Bounded soak uses simultaneous independent authenticated sessions.
    soak_deadline=time.monotonic()+fixture.args.soak_seconds
    def soak(index):
        while time.monotonic()<soak_deadline and not fixture.limit_hit.is_set():
            worker(index, 8, "soak")
            time.sleep(.05)
    with ThreadPoolExecutor(max_workers=fixture.args.workers) as pool:
        list(pool.map(soak, range(fixture.args.workers)))
    before_restart=inventory(fixture.data)
    fixture.stop()
    fixture.start()
    after_restart=inventory(fixture.data)
    metrics.check(before_restart==after_restart, "normal_restart_inventory")
    fixture.stop(hard=True)
    fixture.start()
    after_crash=inventory(fixture.data)
    metrics.check(before_restart==after_crash, "hard_restart_inventory")
    with httpx.Client(trust_env=False, timeout=10) as client:
        for identifier,title in acknowledged.items():
            status, row=request(fixture, metrics, client, "GET", "/api/v1/tasks/"+identifier, actor=owner, phase="persisted_write_verify")
            metrics.check(status==200 and row.get("title")==title, "acknowledged_write_survived")
        for run in queue_records:
            _, row=request(fixture, metrics, client, "GET", "/api/v1/assistant/runs/"+run["id"], actor=owner, phase="persisted_queue_verify")
            metrics.check(row.get("state")==run["state"], "queue_restart_state")
    metrics.check(after_crash["counts"]["tasks"]-baseline["counts"]["tasks"]==len(acknowledged), "task_count_oracle")
    return {"baseline":baseline,"before_restart":before_restart,"after_restart":after_restart,"after_crash":after_crash,
            "acknowledged_writes":len(acknowledged),"assistant_runs":queue_records,"independent_users":len(actors),
            "real_parser_corpus":corpus,"controlled_queue_faults":fault_contracts}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-clean-source", action="store_true")
    for name,default in [("workers",4),("scale-tasks",256),("operations",320),("assistant-runs",8),("soak-seconds",20),
                         ("max-seconds",600),("max-rss-mb",1536),("max-disk-mb",256),("max-cpu-seconds",300),("startup-timeout",180)]:
        parser.add_argument("--"+name,type=int,default=default)
    args=parser.parse_args(argv)
    if args.serve:
        return serve(args.profile.resolve(),args.port)
    if args.output is None or not 1<=args.workers<=8 or not 0<=args.assistant_runs<=24:
        parser.error("New --output, workers1..8, assistant-runs0..24 required")
    if not (0<=args.scale_tasks<=4000 and 1<=args.operations<=10000 and 0<=args.soak_seconds<=120 and 30<=args.max_seconds<=1200):
        parser.error("Bounded workload required")
    if not (256<=args.max_rss_mb<=4096 and 64<=args.max_disk_mb<=1024 and 10<=args.max_cpu_seconds<=600
            and 15<=args.startup_timeout<=240):
        parser.error("CPU/RAM/disk/startup budgets must stay within the documented local bounds")
    output=args.output.resolve()
    if output.exists():
        parser.error("Output must be a new directory; existing evidence is never overwritten")
    output.mkdir(parents=True,exist_ok=False)
    (output/".release-stress-owned.json").write_text(json.dumps({"kind":"synthetic-release-stress","created_at":datetime.now(timezone.utc).isoformat()}),encoding="utf-8")
    metrics=Metrics()
    fixture=Fixture(output,args,metrics)
    report={"schema":"immomanager-release-stress/1","started_at":datetime.now(timezone.utc).isoformat(),"source_before":snapshot(),"workload_started":False,
            "limits":vars(args)|{"output":str(output),"profile":None},"scope":"Own synthetic BW demo, real loopback HTTP, SQLite, local assistant queue; no live-provider/model quality claim. Rate limiter disabled only in this private load fixture. Explicit STRESS-HOLD/STRESS-UNKNOWN requests inject local latency/uncertain failures only in the marked harness server.","status":"failed"}
    monitor=threading.Thread(target=fixture.monitor,daemon=True)
    monitor.start()
    try:
        if args.require_clean_source and not report["source_before"]["clean"]:
            raise RuntimeError("Release gate requires a clean checkout before any workload")
        # Even optional dotenv lookup must stay inside our own new fixture.
        os.chdir(output)
        report["workload_started"] = True
        report["health"]=fixture.start()
        report["workload"]=exercise(fixture,metrics)
    except BaseException as error:
        report["error"]={"type":type(error).__name__,"message":str(error)[:500]}
    finally:
        try:
            fixture.stop()
        except Exception as error:
            report["cleanup_error"]={"type":type(error).__name__,"message":str(error)[:500]}
            if fixture.proc is not None:
                fixture.stop(hard=True)
        fixture.stop_monitor.set()
        monitor.join(timeout=3)
        report.update(source_after=snapshot(),duration_seconds=round(time.monotonic()-fixture.started,3),
            measurements=metrics.summary(),findings=metrics.findings,max_simultaneous_http_requests=metrics.max_active,
            shutdowns=fixture.shutdowns,resource_samples=fixture.samples,resource_limit_hit=fixture.limit_hit.is_set(),
            resource_scope="Harness process and its actual descendants; sampled RSS/CPU, own output directory disk.")
        report["source_unchanged"]=report["source_before"]==report["source_after"]
        report["source_runtime_files_unchanged"]=report["source_before"]["files"]==report["source_after"]["files"]
        report["resource_monitor_error"]=fixture.monitor_error
        if not any(k in report for k in ["error","cleanup_error"]) and not metrics.findings and not fixture.limit_hit.is_set():
            report["status"]="passed"
        report["workload_status"] = report["status"] if report['workload_started'] else 'not_run'
        report["release_eligible"] = source_eligible(report["source_before"], report["source_after"], report["status"]=="passed")
        report["release_eligibility_scope"] = "Source-bound stress gate only; signing, upgrade, security and real model-quality decisions remain independent."
        if args.require_clean_source and not report["release_eligible"]:
            report["status"] = "failed"
        (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
        lines=["# Begrenzter Release-Stresstest", "", "Ergebnis: **"+report["status"]+"**", "", report["scope"], "",
               f'Dauer: {report["duration_seconds"]}s; maximale parallele HTTP-Anfragen: {metrics.max_active}.',"",
               "| Phase | Anzahl | Unerwartet | p50 ms | p95 ms | Maximum ms |", "|---|---:|---:|---:|---:|---:|"]
        lines += [f'| {name} | {m["count"]} | {m["unexpected"]} | {m["p50_ms"]} | {m["p95_ms"]} | {m["max_ms"]} |' for name,m in metrics.summary().items()]
        lines += ["", "Keine Aussage über echte Modellqualität, PostgreSQL-Mehrschreiberkapazität oder langfristigen Dauerbetrieb. Harte Neustarts hier nach bestätigten Schreibvorgängen; Abbruch mitten im Commit ist eine gesonderte Prüfung.", "", "Fehler: "+json.dumps(report.get("error") or metrics.findings,ensure_ascii=False)]
        (output/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(output),"status":report["status"],"duration_seconds":report["duration_seconds"],"findings":len(metrics.findings),"error":report.get("error")},ensure_ascii=True))
    return int(report["status"]!="passed")


if __name__=="__main__":
    raise SystemExit(main())
