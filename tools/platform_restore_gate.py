"""Owned portable restore + real ASGI application gate; stdin holds synthetic credentials.

The coordinator may additionally run platform_restore_browser.mjs against an owned
server. This gate never reports a browser pass from HTTP/ASGI evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def clean_env(target: Path) -> dict:
    """Keep OS essentials, discard ALL inherited application/provider/key configuration."""
    names = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "LANG"}
    env = {key: value for key, value in os.environ.items() if key.upper() in names}
    env.update(PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8", DATA_DIR=str(target),
               DATABASE_URL=f"sqlite:///{(target / 'immo_manager.db').as_posix()}",
               UPLOADS_DIR=str(target / "uploads"), BACKUP_DIR=str(target / "backups"),
               SECRET_KEY_FILE=str(target / "secrets/keyring.json"),
               INTEGRATION_STATE_FILE=str(target / "integrations.json"),
               JOB_SCHEDULER_ENABLED="false", BACKUP_SCHEDULE_ENABLED="false", PLUGIN_DIRS="[]",
               AI_ENABLED="false", AUTO_SEED_DEMO_DATA="false", TASK_QUEUE_BACKEND="sync",
               SQLITE_PERSISTENT_STORE="true", ALLOW_INMEMORY_FALLBACK="false",
               IMMO_RESTORE_PROBE="true", IMMO_TESTVERSION="false")
    return env


def app_gate(spec: dict) -> dict:
    # Imports occur only in the fresh child AFTER CWD/env have been relocated.
    from backend.config import settings
    if settings.job_scheduler_enabled or settings.backup_schedule_enabled or settings.plugin_dirs:
        raise RuntimeError("Probe effects must be disabled")
    from backend.services.integrations.manager import integration_manager
    # Fail closed even if future startup handlers try to execute an integration.
    def disabled(*args, **kwargs):
        raise RuntimeError("Integrations are disabled in restore probe")
    integration_manager.run = disabled
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.services.portable_runtime import inventory
    references, _ = inventory(Path(settings.database_url.removeprefix("sqlite:///")))
    expected = spec["originals"]
    if not references.issubset(expected):
        raise RuntimeError("Every retained reference needs an independent expected original hash")
    timings = []
    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.post("/api/v1/auth/login", json={"username": spec["username"], "password": spec["password"]})
        if response.status_code != 200:
            raise RuntimeError("Restored app login failed")
        timings.append(time.perf_counter() - started)
        token = response.json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        review = client.get("/api/v1/privacy/restore-review", headers=headers)
        if review.status_code != 200:
            raise RuntimeError("Restored privacy gate cannot be inspected")
        privacy_pending = review.json()["pending"]
        # A probe never reconciles or releases real privacy decisions. Verify
        # retained bytes privately while proving that the new HTTP gate stays shut.
        from backend.services.file_storage import LocalStorage
        local = LocalStorage(Path(settings.uploads_dir))
        for key, digest in expected.items():
            started = time.perf_counter()
            response = client.get("/uploads/" + key, headers=headers)
            ranged = client.get("/uploads/" + key, headers={**headers, "Range": "bytes=0-3"})
            if privacy_pending:
                content = local.get(key)
                if content is None or hashlib.sha256(content).hexdigest() != digest:
                    raise RuntimeError("Restored private original differs")
                if response.status_code != 503 or ranged.status_code != 503:
                    raise RuntimeError("Restored original bypasses pending privacy review")
            else:
                if response.status_code != 200 or hashlib.sha256(response.content).hexdigest() != digest:
                    raise RuntimeError("Restored authenticated original differs")
                if ranged.status_code != 206 or ranged.content != response.content[:4]:
                    raise RuntimeError("Restored original Range gate failed")
            if TestClient(app).get("/uploads/" + key).status_code != 401:
                raise RuntimeError("Restored original is public")
            timings.append(time.perf_counter() - started)
    return {"ok": True, "readiness": "application_verified", "login": True,
            "access_readiness": "privacy_review_required" if privacy_pending else "reviewed",
            "privacy_review_released_by_probe": False,
            "originals": len(expected), "attachment_references": len(references),
            "browser": "not_run", "schedulers": "disabled", "integrations": "disabled",
            "durations_s": timings}


def restore_and_gate(archive: Path, target: Path, spec: dict) -> dict:
    if not target.resolve().is_relative_to(ROOT / "artifacts"):
        raise ValueError("Probe target must be a fresh owned checkout artifacts directory")
    from backend.services.full_backup import restore_archive
    restored = restore_archive(archive, target, passphrase=spec.pop("passphrase"))
    if restored["dialect"] != "sqlite":
        raise ValueError("PostgreSQL needs a coordinator-owned fresh database gate")
    # Upgrade is explicit, on the restored copy only, with pre-upgrade archives in a fresh folder.
    env = clean_env(target)
    env["BACKUP_PASSPHRASE"] = spec.pop("migration_passphrase", "synthetic-probe-backup-only")
    upgrade = subprocess.run([sys.executable, "-m", "backend.upgrade"], cwd=target, env=env,
                             capture_output=True, timeout=90)
    if upgrade.returncode:
        from backend.services.secret_box import write_private_file
        write_private_file(target / "upgrade-probe.log", upgrade.stdout + upgrade.stderr)
        raise RuntimeError("Owned restored-copy upgrade failed; original archive is unchanged")
    result = subprocess.run([sys.executable, "-m", "tools.platform_restore_gate", "--worker"],
        cwd=target, env=env, input=json.dumps(spec), text=True, capture_output=True, timeout=90)
    if result.returncode:
        from backend.services.secret_box import write_private_file
        write_private_file(target / "application-probe.log", (result.stdout + result.stderr).encode("utf-8"))
        raise RuntimeError("Owned restored app gate failed (child output retained privately by caller)")
    lines = [line for line in result.stdout.splitlines() if line.startswith("PLATFORM_GATE=")]
    if len(lines) != 1:
        raise RuntimeError("Application gate did not return a complete receipt")
    return {"restore": restored, **json.loads(lines[0].split("=", 1)[1])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    spec = json.load(sys.stdin)
    result = app_gate(spec) if args.worker else restore_and_gate(args.archive, args.target, spec)
    print("PLATFORM_GATE=" + json.dumps(result))


if __name__ == "__main__":
    main()
