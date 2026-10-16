"""Opt-in real source/report/document/job/restore phases for the owned scale fixture.

No cardinality runs execute on import. PostgreSQL and browser coverage are explicit
separate gates; an omitted gate cannot become a complete platform acceptance.
"""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from uuid import uuid4

from tools.scale_finance_search import FILTERS, PASSWORD, cents, require
from tools.scale_runtime import resource_sample


def distribution(values):
    if not values:
        raise ValueError("A completed phase needs actual measurements")
    values = sorted(values)
    return {"samples": len(values), "p50": values[len(values) // 2],
            "p95": values[math.ceil(len(values) * .95) - 1], "max": values[-1]}


def run_platform(run):
    result = {"backend": "sqlite", "source": {}, "report": {}, "document": {}, "job": {},
              "restore": {}, "browser": {"status": "not_run"}, "PostgreSQL": {"status": "not_run"}}
    run.data["platform"] = result
    run.phase("platform_sources")
    expected = {f"contract:contract-{index:03d}" for index in range(300)}
    saved = []
    for index in range(300):
        identifier = f"contract-{index:03d}"
        source = run.call(run.owner, "GET", f"/workspace/source/contract/{identifier}")
        command = {"action": "favorite.set", "source_kind": "contract", "source_id": identifier,
                   "source_revision": source["revision"], "base_revision": 0,
                   "idempotency_key": str(uuid4()), "confirmed": True}
        item = run.call(run.owner, "POST", "/workspace/actions", payload=command)
        require(run.call(run.owner, "POST", "/workspace/actions", payload=command) == item, "Action replay differs")
        saved.append(item["id"])
    seen, cursor, cursors = set(), None, set()
    while True:
        page = run.call(run.owner, "GET", "/workspace/favorites", params={"limit": 37, **({"cursor": cursor} if cursor else {})})
        for item in page["items"]:
            require(item["id"] not in seen, "Duplicate source page ID")
            seen.add(item["id"])
        cursor = page["next_cursor"]
        if not cursor:
            break
        require(cursor not in cursors, "Source cursor did not advance")
        cursors.add(cursor)
    require(seen == expected and set(saved) == expected, "Source pagination omitted expected IDs")
    result["source"] = {"expected_ids": sorted(expected), "actual_ids": sorted(seen),
                        "writes_acknowledged": 300, "writes_verified": 300}

    run.phase("platform_period_report")
    report = run.call(run.owner, "GET", "/reports/period-result", params=FILTERS["all"])
    # Independent ten-record fixture recipe: 1111 other income, 7777 costs per group.
    # Every one of 300 synthetic contracts owes 800 EUR in each of 240 full months.
    groups = run.args.rows // 10
    expected_cents = {"rent_due": 300 * 240 * 80000, "other_income": groups * 1111,
                      "costs": groups * 7777, "unassigned_income": groups * 7777,
                      "result": 300 * 240 * 80000 - groups * 6666}
    require(len(report["monthly"]) == 240, "Period report omitted months")
    for field, amount in expected_cents.items():
        require(cents(report["totals"][field]) == amount, "Independent period cents differ: " + field)
    result["report"] = {"expected_cents": expected_cents, "months": 240, "writes": 0}

    run.phase("platform_documents")
    original = b"Synthetic retained original\x00\xff\n"
    _, client = run.owner
    started = time.perf_counter()
    upload = client.post("/files/upload", files={"file": ("original.txt", original, "text/plain")})
    require(upload.status_code == 200, "Synthetic original upload failed")
    file_url = upload.json()["file_url"]
    require(file_url.startswith("/uploads/"), "Original lacks canonical private URL")
    documents = []
    for index in range(run.args.platform_documents):
        item = run.call(run.owner, "POST", "/documents", expect=201,
                        payload={"title": f"Platform original {index}", "file_url": file_url,
                                 "property_id": "prop-00", "document_type": "other"})
        documents.append(item["id"])
    response = client.get(run.server.base.removesuffix("/api/v1") + file_url)
    require(response.status_code == 200 and response.content == original, "Original download changed")
    digest = hashlib.sha256(original).hexdigest()
    result["document"] = {"expected_ids": documents, "expected_sha256": digest,
                          "writes_acknowledged": len(documents), "writes_verified": 0,
                          "latency_s": time.perf_counter() - started}
    with closing(sqlite3.connect(run.server.db_file)) as db:
        actual = {row[0] for row in db.execute("SELECT id FROM documents WHERE file_url=?", (file_url,))}
    require(actual == set(documents), "Acknowledged document IDs were not persisted exactly")
    result["document"]["writes_verified"] = len(actual)

    run.phase("platform_backup_job_restore")
    from sqlalchemy import create_engine
    from backend.services.jobs.core import SqlJobStore, JobRunner
    from backend.services.full_backup import Sources, create_full_backup
    from tools.platform_restore_gate import restore_and_gate
    sources = Sources(database_url=f"sqlite:///{run.server.db_file.as_posix()}", data_dir=run.server.dir,
        uploads_dir=run.server.dir / "uploads", root=run.server.dir / "backups/full",
        integration_state=run.server.dir / "integrations.json", key_file=run.server.dir / "secrets/keyring.json",
        env_file=run.server.dir / ".env", passphrase="synthetic-platform-backup-only",
        runtime_bytes=json.dumps({"jwt_secret_key": run.server.secret, "environment": "development"}).encode())
    archive_receipt = {}
    def backup(ctx):
        archive_receipt.update(create_full_backup(sources=sources, heartbeat=ctx.heartbeat))
        with ctx.unit() as unit:
            unit.save({"archive": archive_receipt["archive"]}, {"files": archive_receipt["uploads"]})
        return True
    engine = create_engine(sources.database_url)
    try:
        jobs = SqlJobStore(engine)
        job = jobs.enqueue("platform.scale.backup", "platform-scale-backup")
        require(jobs.enqueue("platform.scale.backup", "platform-scale-backup").id == job.id, "Duplicate backup job")
        job = JobRunner(jobs, {"platform.scale.backup": backup}).run_one()
        require(job.status == "succeeded", "Persistent backup job did not succeed: " + str(job.last_error))
        result["job"] = {"expected_ids": [job.id], "writes_acknowledged": 1, "writes_verified": 1}
    finally:
        engine.dispose()
    restored = restore_and_gate(sources.root / archive_receipt["archive"], run.out / "portable-restored",
        {"passphrase": sources.passphrase, "username": "scaleowner", "password": PASSWORD,
         "originals": {file_url.removeprefix("/uploads/"): digest}})
    require(restored["ok"], "Standalone restore app gate failed")
    result["restore"] = restored
    if run.args.platform_browser_module:
        run.phase("platform_browser")
        browser = subprocess.run(["node", str(Path(__file__).with_name("platform_restore_browser.mjs"))],
            input=json.dumps({"base": run.server.base.removesuffix("/api/v1"), "username": "scaleowner",
                              "password": PASSWORD, "originals": {file_url.removeprefix("/uploads/"): digest},
                              "screenshot": str(run.out / "platform-browser.png")}),
            env={**os.environ, "PLAYWRIGHT_MODULE": str(run.args.platform_browser_module)},
            capture_output=True, text=True, timeout=90)
        require(browser.returncode == 0, "Owned platform browser gate failed")
        result["browser"] = json.loads(browser.stdout.splitlines()[-1])
    result["parent_resource_sample"] = resource_sample(os.getpid())
    result["acceptance"] = "sqlite_application_verified"  # PG remains a separate required run.
    run.checkpoint("platform_phases_verified", result)
