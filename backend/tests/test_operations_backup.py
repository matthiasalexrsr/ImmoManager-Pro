"""Secrets at rest, full backups, restore probes, retention, schedule, explicit upgrade, overview."""

import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend import auth
from backend.config import settings
from backend.db import schema_state
from backend.services import full_backup, secret_box
from backend.services.full_backup import Archive, Sources
from backend.services.integrations.config_store import JsonFileIntegrationConfigStore
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import ContractWizardProvider, EmailIntegrationProvider
from backend.services.jobs import scheduler
from backend.services.jobs.core import Handler, MemoryJobStore
from backend.services.jobs.schedule import MonthlyAt
from backend.storage import InMemoryStore

ROOT = Path(__file__).resolve().parents[2]
SMTP = {"sender_email": "office@example.test", "smtp_host": "smtp.example.test", "smtp_user": "office",
        "smtp_password": "test-only-password"}
OLD_REVISION = "a7c2e9f4b1d3"           # portfolio access, before durable jobs


def _manager(data: Path, box=None) -> IntegrationManager:
    manager = IntegrationManager(store=JsonFileIntegrationConfigStore(str(data / "integrations.json")),
                                 secret_box=box)
    manager.register(EmailIntegrationProvider())
    manager.register(ContractWizardProvider())
    manager._load_state()
    return manager


def _stored(data: Path) -> dict:
    return json.loads((data / "integrations.json").read_text(encoding="utf-8"))


def _seed(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            INSERT INTO portfolios (id, name, currency, timezone, status, created_at, updated_at)
                VALUES ('pf1', 'Nord', 'EUR', 'Europe/Berlin', 'active', '2025-01-01', '2025-01-01'),
                       ('pf2', 'Süd', 'EUR', 'Europe/Berlin', 'active', '2025-01-01', '2025-01-01');
            INSERT INTO users (id, username, email, full_name, hashed_password, role, is_active, totp_enabled,
                               created_at, updated_at)
                VALUES ('staff', 'staff', 's@example.com', 'Staff', 'x', 'verwalter', 1, 0,
                        '2025-01-01', '2025-01-01');
        """)


def _migrate(url: str, revision: str) -> None:
    command.upgrade(schema_state.alembic_config(url), revision)


@pytest.fixture
def installation(tmp_path):
    """A data directory as the desktop program keeps it: DB at the head, uploads, settings, key, .env."""
    data = tmp_path / "data"
    uploads = data / "uploads"
    (uploads / "documents").mkdir(parents=True)
    (uploads / "photos" / "2026").mkdir(parents=True)
    (uploads / "documents" / "vertrag.pdf").write_bytes(b"%PDF-1.4 contract " * 200)
    (uploads / "photos" / "2026" / "zähler.jpg").write_bytes(bytes(range(256)) * 40)
    db = data / "immo_manager.db"
    engine = create_engine(f"sqlite:///{db}")
    schema_state.initialise_empty(engine)
    engine.dispose()
    _seed(db)
    box = secret_box.SecretBox(data / "secrets" / "keyring.json")
    manager = _manager(data, box)
    manager.update_config("email", SMTP)
    assert manager.run("contract-wizard", {"tenant_name": "Mia"})["success"]     # creates the journal
    (data / ".env").write_text(f"DATA_DIR={data}\nJWT_SECRET_KEY=test-only-not-a-real-secret\n", encoding="utf-8")
    sources = Sources(database_url=f"sqlite:///{db}", data_dir=data, uploads_dir=uploads,
                      root=data / "backups" / "full", integration_state=data / "integrations.json",
                      key_file=box.key_file, env_file=data / ".env")
    return SimpleNamespace(data=data, db=db, box=box, sources=sources, manager=manager)


@pytest.fixture
def configured(installation, monkeypatch):
    """The same installation behind the process settings (job handlers, upgrade, API)."""
    data = installation.data
    for name, value in {"data_dir": str(data), "uploads_dir": str(data / "uploads"),
                        "backup_dir": str(data / "backups"), "database_url": f"sqlite:///{installation.db}",
                        "integration_state_file": str(data / "integrations.json"),
                        "secret_key_file": str(installation.box.key_file), "secret_keys": "",
                        "backup_passphrase": "", "backup_second_target": ""}.items():
        monkeypatch.setattr(settings, name, value)
    return installation


# --- secrets at rest -----------------------------------------------------------------------

def test_secret_round_trip_with_key_id_and_owner_only_key_file(tmp_path):
    box = secret_box.SecretBox(tmp_path / "secrets" / "keyring.json")
    token = box.seal("smtp-password", "integrations/email/smtp_password")
    assert token.startswith(f"enc:v1:{box.active_key_id()}:")
    assert "smtp-password" not in token
    assert box.open(token, "integrations/email/smtp_password") == "smtp-password"
    with pytest.raises(secret_box.SecretCorrupt):           # bound to its field
        box.open(token, "integrations/whatsapp/api_token")
    if os.name != "nt":
        assert box.key_file.stat().st_mode & 0o777 == 0o600
        assert box.key_file.parent.stat().st_mode & 0o777 == 0o700


def test_rotation_keeps_old_values_readable_and_reseals_with_the_new_key(installation):
    old_key = installation.box.active_key_id()
    new_key = installation.box.rotate()
    assert new_key != old_key and installation.box.key_ids() == [new_key, old_key]
    restarted = _manager(installation.data, installation.box)
    assert restarted.persistence_error is None
    assert restarted.reseal() == 1
    assert secret_box.token_key_id(_stored(installation.data)["config"]["email"]["smtp_password"]) == new_key
    assert restarted.secret_status()["key_ids_in_use"] == [new_key]


def test_secrets_are_stored_encrypted_and_never_returned(installation):
    stored = _stored(installation.data)["config"]["email"]["smtp_password"]
    assert secret_box.is_sealed(stored) and "test-only-password" not in (installation.data / "integrations.json").read_text()
    details = installation.manager.get_integration("email")
    assert details["config"]["smtp_password"] == "***"
    assert "test-only-password" not in json.dumps(details)
    status = installation.manager.secret_status()
    assert status["sealed"] == 1 and status["plaintext"] == 0
    assert "test-only-password" not in json.dumps(status)
    # the masked value sent back keeps the stored secret
    installation.manager.update_config("email", details["config"])
    assert _manager(installation.data, installation.box)._config["email"]["smtp_password"] == "test-only-password"


def test_plaintext_secrets_are_encrypted_on_load_without_loss(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "integrations.json").write_text(json.dumps({"enabled": {"email": True},
                                                        "config": {"email": SMTP}}), encoding="utf-8")
    box = secret_box.SecretBox(data / "secrets" / "keyring.json")
    manager = _manager(data, box)
    stored = _stored(data)["config"]["email"]
    assert secret_box.is_sealed(stored["smtp_password"])
    assert {k: v for k, v in stored.items() if k != "smtp_password"} == {k: v for k, v in SMTP.items()
                                                                         if k != "smtp_password"}
    assert manager._config["email"]["smtp_password"] == "test-only-password"
    assert manager.get_integration("email")["configured"] is True


def test_a_missing_key_is_an_error_not_a_reset(installation, tmp_path):
    before = (installation.data / "integrations.json").read_bytes()
    elsewhere = secret_box.SecretBox(tmp_path / "other" / "keyring.json")
    manager = _manager(installation.data, elsewhere)
    error = manager.persistence_error
    assert error and installation.box.active_key_id() in error and "Vollbackup" in error
    assert "smtp_password" not in manager.get_integration("email")["config"]
    with pytest.raises(OSError):
        manager.update_config("email", {"smtp_host": "other.example.test"})
    assert (installation.data / "integrations.json").read_bytes() == before
    assert not elsewhere.key_file.exists()                 # no new key was made up


def test_api_shows_the_lock_reason_but_never_a_secret(installation, monkeypatch):
    from backend.app import app
    from backend.routers import integrations

    manager = _manager(installation.data, secret_box.SecretBox(installation.data / "missing.json"))
    monkeypatch.setattr(integrations, "integration_manager", manager)
    auth.clear_users()
    owner = auth.register_user("ops-owner", "ops-owner@example.test", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {auth.create_access_token(owner.id)}"}
    client = TestClient(app)
    response = client.put("/api/v1/integrations/email/config", headers=headers,
                          json={"config": {"smtp_host": "x.example.test"}})
    assert response.status_code == 503 and "Schlüssel" in response.text and "gesperrt" in response.text
    listing = client.get("/api/v1/integrations", headers=headers).text
    assert "test-only-password" not in listing and "enc:v1:" not in listing
    auth.clear_users()


def test_tampered_ciphertext_locks_writes(installation):
    state = _stored(installation.data)
    token = state["config"]["email"]["smtp_password"]
    state["config"]["email"]["smtp_password"] = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    (installation.data / "integrations.json").write_text(json.dumps(state), encoding="utf-8")
    manager = _manager(installation.data, installation.box)
    assert manager.persistence_error and "verändert" in manager.persistence_error


def test_keys_from_the_environment_write_no_key_file(tmp_path):
    material = secret_box.new_key_material()
    box = secret_box.SecretBox(tmp_path / "keyring.json", material)
    token = box.seal("value", "ctx")
    assert str(box.active_key_id()).startswith("env-") and not box.key_file.exists()
    assert secret_box.SecretBox(tmp_path / "keyring.json", f"{secret_box.new_key_material()},{material}") \
        .open(token, "ctx") == "value"
    with pytest.raises(secret_box.SecretError):
        secret_box.SecretBox(tmp_path / "x.json", "dG9vLXNob3J0")


def test_passphrase_envelope(tmp_path):
    sealed = secret_box.seal_with_passphrase(b"keys", "correct horse")
    assert b"keys" not in sealed
    assert secret_box.open_with_passphrase(sealed, "correct horse") == b"keys"
    with pytest.raises(secret_box.SecretError):
        secret_box.open_with_passphrase(sealed, "wrong")


# --- full backup, verification, tamper detection -----------------------------------------------

def test_full_backup_contains_everything_and_verifies(installation):
    event = full_backup.create_full_backup("manual", installation.sources)
    archive = installation.sources.root / event["archive"]
    assert event["ok"] and archive.is_file() and not list(installation.sources.root.glob("*.partial"))
    assert (archive.with_name(archive.name + ".sha256")).read_text().split()[0] == event["sha256"]
    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        names = set(zf.namelist())
    assert {"database/immo_manager.sqlite3", "uploads/documents/vertrag.pdf", "uploads/photos/2026/zähler.jpg",
            "config/integrations.json", "config/integrations-journal.sqlite3", "secrets/keyring.json",
            "config/env", "manifest.json"} == names
    assert manifest["database"]["revision"] == schema_state.head_revision() == manifest["alembic_head"]
    assert manifest["database"]["row_counts"]["portfolios"] == 2
    assert manifest["app_version"] == settings.app_version
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])
    assert manifest["secrets"]["needed_key_ids"] == [installation.box.active_key_id()]
    assert manifest["secrets"]["missing_key_ids"] == []
    report = full_backup.verify_archive(archive, expected_sha256=event["sha256"])
    assert report["ok"], report["problems"]


def _rewrite(archive: Path, target: Path, *, replace: dict | None = None, add: dict | None = None) -> Path:
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(target, "w") as out:
        for item in source.infolist():
            out.writestr(item, (replace or {}).get(item.filename, source.read(item.filename)))
        for name, data in (add or {}).items():
            out.writestr(name, data)
    return target


def test_tampering_is_detected(installation, tmp_path):
    event = full_backup.create_full_backup("manual", installation.sources)
    archive = installation.sources.root / event["archive"]

    changed = _rewrite(archive, tmp_path / "changed.zip", replace={"uploads/documents/vertrag.pdf": b"%PDF forged"})
    report = full_backup.verify_archive(changed)
    assert not report["ok"] and any("vertrag.pdf" in problem for problem in report["problems"])

    extra = _rewrite(archive, tmp_path / "extra.zip", add={"uploads/evil.exe": b"MZ"})
    assert any("Nicht im Manifest" in p for p in full_backup.verify_archive(extra)["problems"])

    traversal = _rewrite(archive, tmp_path / "traversal.zip", add={"../outside.txt": b"x"})
    assert any("Unsichere Pfade" in p for p in full_backup.verify_archive(traversal)["problems"])

    raw = bytearray(archive.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    flipped = archive.with_name("flipped.zip")
    flipped.write_bytes(bytes(raw))
    (flipped.with_name("flipped.zip.sha256")).write_text(f"{event['sha256']}  flipped.zip\n")
    problems = full_backup.verify_archive(flipped)["problems"]
    assert any(".sha256" in p for p in problems)

    assert not full_backup.verify_archive(archive, expected_sha256="0" * 64)["ok"]


def test_restore_probe_opens_checks_and_removes_the_copy(installation):
    full_backup.create_full_backup("manual", installation.sources)
    event = full_backup.restore_probe(sources=installation.sources)
    checks = event["checks"]
    assert event["ok"] and checks["row_counts_match"] and checks["revision"] == schema_state.head_revision()
    assert checks["uploads"] == 2 and checks["secrets"] == {"sealed_values": 1, "decrypted": 1, "warning": None}
    assert checks["probe_dir_removed"] and not list(installation.sources.root.glob(".probe-*"))
    assert event["warnings"] == []
    logged = full_backup.read_events(installation.sources.root)
    assert [e["event"] for e in logged[:2]] == ["restore_probe", "backup"]


def test_restore_probe_fails_on_a_tampered_archive_and_logs_it(installation):
    event = full_backup.create_full_backup("manual", installation.sources)
    archive = installation.sources.root / event["archive"]
    forged = _rewrite(archive, archive.with_name("forged.zip"), replace={"config/env": b"JWT_SECRET_KEY=forged\n"})
    os.replace(forged, archive)                     # same name, sidecar now wrong
    with pytest.raises(full_backup.BackupError, match="Archivprüfung"):
        full_backup.restore_probe(sources=installation.sources)
    assert full_backup.read_events(installation.sources.root)[0]["ok"] is False


def test_passphrase_protects_the_archived_keys(installation):
    installation.sources.passphrase = "operator passphrase"
    event = full_backup.create_full_backup("manual", installation.sources)
    with zipfile.ZipFile(installation.sources.root / event["archive"]) as zf:
        names = set(zf.namelist())
        sealed = zf.read("secrets/secrets.enc")
    assert "secrets/keyring.json" not in names and "config/env" not in names
    assert b"test-only-not-a-real-secret" not in sealed
    without = full_backup.restore_probe(sources=installation.sources, passphrase="")
    assert any("Passphrase" in w for w in without["warnings"])
    probed = full_backup.restore_probe(sources=installation.sources)
    assert probed["checks"]["secrets"]["decrypted"] == 1


def test_probe_of_an_older_backup_tests_the_upgrade(tmp_path):
    db = tmp_path / "old.db"
    url = f"sqlite:///{db}"
    _migrate(url, OLD_REVISION)
    _seed(db)
    sources = Sources(database_url=url, data_dir=tmp_path, uploads_dir=tmp_path / "uploads", root=tmp_path / "full",
                      integration_state=tmp_path / "integrations.json", key_file=tmp_path / "keyring.json",
                      env_file=tmp_path / ".env")
    full_backup.create_full_backup("manual", sources)
    event = full_backup.restore_probe(sources=sources)
    assert event["checks"]["revision"] == OLD_REVISION and event["checks"]["upgrade_to_head_tested"]
    assert any("backend.upgrade" in w for w in event["warnings"])
    assert schema_state.inspect_url(url).revision == OLD_REVISION          # the live file stays as it was


def test_restore_builds_a_new_data_directory(installation, tmp_path):
    event = full_backup.create_full_backup("manual", installation.sources)
    target = tmp_path / "restored"
    result = full_backup.restore_archive(installation.sources.root / event["archive"], target)
    assert result["revision"] == schema_state.head_revision()
    assert (target / "uploads" / "documents" / "vertrag.pdf").read_bytes() == \
        (installation.data / "uploads" / "documents" / "vertrag.pdf").read_bytes()
    assert (target / "secrets" / "keyring.json").read_bytes() == installation.box.key_file.read_bytes()
    env = (target / ".env").read_text()
    assert "DATA_DIR" not in env and "JWT_SECRET_KEY=test-only-not-a-real-secret" in env
    assert "DATA_DIR" in (target / ".env.from-backup").read_text()
    restored = _manager(target, secret_box.SecretBox(target / "secrets" / "keyring.json"))
    assert restored.persistence_error is None
    assert restored._config["email"]["smtp_password"] == "test-only-password"
    with sqlite3.connect(target / "immo_manager.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0] == 2
    with pytest.raises(full_backup.BackupError, match="nicht leer"):
        full_backup.restore_archive(installation.sources.root / event["archive"], target)


def test_second_target_gets_a_verified_copy(installation, tmp_path):
    installation.sources.second_target = tmp_path / "share"
    event = full_backup.create_full_backup("manual", installation.sources)
    copy = tmp_path / "share" / event["archive"]
    assert event["second_target"]["ok"] and full_backup.sha256_file(copy) == event["sha256"]
    assert full_backup.verify_archive(copy)["ok"]
    overview = full_backup.overview(installation.sources)
    assert overview["backup"]["archives"][0]["on_second_target"] is True
    assert "no_second_target" not in {w["code"] for w in overview["warnings"]}


def test_a_failing_second_target_is_reported_and_the_backup_kept(installation, tmp_path):
    blocked = tmp_path / "share"
    blocked.write_text("not a directory")
    installation.sources.second_target = blocked
    event = full_backup.create_full_backup("manual", installation.sources)
    assert event["ok"] and event["second_target"]["ok"] is False
    assert (installation.sources.root / event["archive"]).is_file()
    codes = {w["code"] for w in full_backup.overview(installation.sources)["warnings"]}
    assert "second_target_failed" in codes


def test_failures_are_logged_and_concurrent_runs_refused(installation):
    installation.db.unlink()
    with pytest.raises(full_backup.BackupError, match="nicht gefunden"):
        full_backup.create_full_backup("manual", installation.sources)
    assert not installation.db.exists()                    # never created by the backup
    overview = full_backup.overview(installation.sources)
    assert {"last_backup_failed", "no_backup"} <= {w["code"] for w in overview["warnings"]}
    with full_backup._Lock(installation.sources.root):
        with pytest.raises(full_backup.BackupError, match="läuft gerade"):
            full_backup.create_full_backup("manual", installation.sources)


def test_postgres_without_pg_dump_is_refused_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(full_backup.shutil, "which", lambda *args, **kwargs: None)
    sources = Sources(database_url="postgresql://immo@127.0.0.1:1/immo", data_dir=tmp_path,
                      uploads_dir=tmp_path, root=tmp_path / "full", integration_state=tmp_path / "i.json",
                      key_file=tmp_path / "k.json", env_file=tmp_path / ".env")
    with pytest.raises(full_backup.BackupError, match="pg_dump nicht gefunden"):
        full_backup.create_full_backup("manual", sources)


# --- retention -------------------------------------------------------------------------------

def _archive(directory: Path, moment: datetime, trigger: str = "scheduled") -> Archive:
    name = f"immomanager-full-{moment.strftime('%Y%m%dT%H%M%S')}Z-{trigger}-{os.urandom(2).hex()}.zip"
    (directory / name).write_bytes(b"x")
    (directory / (name + ".sha256")).write_text("x")
    return Archive(directory / name, moment, trigger)


def test_retention_keeps_daily_monthly_and_pre_upgrade_archives(tmp_path):
    start = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    daily = [_archive(tmp_path, start + timedelta(days=n)) for n in range(280)]      # Jan 1 .. Oct 7
    extra_today = _archive(tmp_path, daily[-1].created_at + timedelta(hours=2), "manual")
    upgrades = [_archive(tmp_path, start + timedelta(days=n, hours=1), "pre-upgrade") for n in (10, 100, 200, 250)]
    removed = full_backup.apply_retention(tmp_path, 14, 6, 3)
    kept = full_backup.list_archives(tmp_path)
    kept_names = {a.name for a in kept}
    assert extra_today.name in kept_names and daily[-1].name not in kept_names     # newest per day only
    days = {a.local_date for a in kept if a.trigger != "pre-upgrade"}
    assert len([d for d in days if d >= daily[-14].local_date]) == 14
    months = {(a.local_date.year, a.local_date.month) for a in kept}
    assert len(months) >= 6
    assert {u.name for u in upgrades[1:]} <= kept_names and upgrades[0].name not in kept_names
    # 14 days (Sep 24 .. Oct 7), 4 older month ends (May .. Aug), the 3 newest pre-upgrade archives
    assert len(kept) == 14 + 4 + 3
    assert not any((tmp_path / (name + ".sha256")).exists() for name in removed)


# --- schedule --------------------------------------------------------------------------------

def test_backup_runs_once_per_day_and_the_probe_once_per_month(monkeypatch):
    from backend import dependencies

    monkeypatch.setattr(settings, "backup_schedule_enabled", True)
    monkeypatch.setattr(dependencies, "_scoped_session", object())
    jobs = MemoryJobStore(store_factory=InMemoryStore)
    moment = datetime(2026, 9, 29, 0, 0)
    while moment < datetime(2026, 10, 3, 0, 0):           # 10-minute ticks over four days
        scheduler.enqueue_due(jobs, moment)
        moment += timedelta(minutes=10)
    runs = jobs.list_runs(limit=1000)
    backups = sorted(r.idempotency_key for r in runs if r.kind == scheduler.BACKUP_KIND)
    probes = sorted(r.idempotency_key for r in runs if r.kind == scheduler.PROBE_KIND)
    # 01:30 Berlin is 23:30 UTC of the day before: the first tick already sees the 29th's slot
    assert backups == [f"{scheduler.BACKUP_KIND}@{day}" for day in
                       ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03")]
    assert probes == [f"{scheduler.PROBE_KIND}@2026-09-01", f"{scheduler.PROBE_KIND}@2026-10-01"]
    assert all(r.max_attempts == 3 for r in runs if r.kind in (scheduler.BACKUP_KIND, scheduler.PROBE_KIND))


def test_no_ops_jobs_without_a_database_or_when_disabled(monkeypatch):
    from backend import dependencies

    monkeypatch.setattr(dependencies, "_scoped_session", None)
    monkeypatch.setattr(settings, "backup_schedule_enabled", True)
    assert scheduler.ops_periodic() == ()
    monkeypatch.setattr(dependencies, "_scoped_session", object())
    monkeypatch.setattr(settings, "backup_schedule_enabled", False)
    assert scheduler.ops_periodic() == ()


def test_monthly_slot_is_clamped_and_berlin_based():
    schedule = MonthlyAt(31, 3, 30)
    assert schedule.latest_due(datetime(2026, 3, 1, 12, 0)) == datetime(2026, 2, 28).date()
    assert schedule.latest_due(datetime(2026, 4, 30, 1, 29)) == datetime(2026, 3, 31).date()   # 03:30 CEST
    assert schedule.latest_due(datetime(2026, 4, 30, 1, 30)) == datetime(2026, 4, 30).date()
    first = MonthlyAt(1, 3, 30)
    assert first.latest_due(datetime(2026, 10, 1, 1, 29)) == datetime(2026, 9, 1).date()


def test_the_scheduled_jobs_back_up_and_probe(configured, monkeypatch):
    from backend import dependencies

    monkeypatch.setattr(settings, "backup_schedule_enabled", True)
    monkeypatch.setattr(dependencies, "_scoped_session", object())
    jobs = MemoryJobStore(store_factory=InMemoryStore)
    handlers: dict[str, Handler] = {scheduler.BACKUP_KIND: scheduler.backup_handler,
                                    scheduler.PROBE_KIND: scheduler.probe_handler}
    runner = scheduler.JobRunner(jobs, handlers)
    scheduler.enqueue_due(jobs, datetime(2026, 10, 1, 4, 0), scheduler.ops_periodic())
    done = runner.run_until_idle()
    assert sorted((run.kind, run.status) for run in done) == [(scheduler.BACKUP_KIND, "succeeded"),
                                                              (scheduler.PROBE_KIND, "succeeded")]
    backup_run = next(run for run in done if run.kind == scheduler.BACKUP_KIND)
    assert backup_run.progress is not None
    assert (configured.data / "backups" / "full" / backup_run.progress["archive"]).is_file()
    scheduler.enqueue_due(jobs, datetime(2026, 10, 1, 9, 0), scheduler.ops_periodic())
    assert runner.run_until_idle() == []                     # same day, same month: nothing new


# --- explicit upgrade ------------------------------------------------------------------------

@pytest.fixture
def outdated(configured):
    """The installation's database replaced by one at an older revision (with data)."""
    configured.db.unlink()
    _migrate(f"sqlite:///{configured.db}", OLD_REVISION)
    _seed(configured.db)
    return configured


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_start_refuses_an_outdated_schema_without_changing_it(outdated):
    engine = create_engine(f"sqlite:///{outdated.db}")
    before = _tables(outdated.db)
    with pytest.raises(schema_state.SchemaUpgradeRequired) as refused:
        schema_state.ensure_current(engine)
    engine.dispose()
    assert OLD_REVISION in str(refused.value) and "python -m backend.upgrade" in str(refused.value)
    assert _tables(outdated.db) == before and "job_runs" not in before
    assert schema_state.inspect_url(f"sqlite:///{outdated.db}").revision == OLD_REVISION


def test_explicit_upgrade_takes_a_full_backup_first(outdated):
    from backend.upgrade import EXIT_NEEDS_UPGRADE, EXIT_OK, upgrade

    lines: list[str] = []
    assert upgrade(check_only=True, out=lines.append) == EXIT_NEEDS_UPGRADE
    assert schema_state.inspect_url(settings.database_url).revision == OLD_REVISION
    assert upgrade(out=lines.append) == EXIT_OK
    assert schema_state.inspect_url(settings.database_url).state == schema_state.CURRENT
    archives = full_backup.list_archives(outdated.data / "backups" / "full")
    assert [a.trigger for a in archives] == ["pre-upgrade"]
    with zipfile.ZipFile(archives[0].path) as zf:
        assert json.loads(zf.read("manifest.json"))["database"]["revision"] == OLD_REVISION
    events = full_backup.read_events(outdated.data / "backups" / "full")
    assert events[0]["event"] == "upgrade" and events[0]["ok"] and events[0]["backup"] == archives[0].name
    assert upgrade(out=lines.append) == EXIT_OK              # second run: nothing to do, no new backup
    assert len(full_backup.list_archives(outdated.data / "backups" / "full")) == 1


def test_upgrade_is_not_run_when_the_backup_fails(outdated):
    from backend.upgrade import EXIT_BACKUP_FAILED, upgrade

    blocked = outdated.data / "backups"
    blocked.mkdir(exist_ok=True)
    (blocked / "full").write_text("not a directory")
    assert upgrade(out=lambda line: None) == EXIT_BACKUP_FAILED
    assert schema_state.inspect_url(settings.database_url).revision == OLD_REVISION


def test_a_newer_database_is_never_touched(configured):
    from backend.upgrade import EXIT_NEWER, upgrade

    with sqlite3.connect(configured.db) as conn:
        conn.execute("UPDATE alembic_version SET version_num = 'ffffffffffff'")
    assert upgrade(out=lambda line: None) == EXIT_NEWER
    engine = create_engine(settings.database_url)
    with pytest.raises(schema_state.SchemaUpgradeRequired, match="neueren Programmversion"):
        schema_state.ensure_current(engine)
    engine.dispose()
    assert not (configured.data / "backups" / "full").exists()


def test_legacy_unversioned_desktop_database_is_adopted_by_the_upgrade(configured):
    from backend.db.orm_models import Base
    from backend.upgrade import EXIT_OK, upgrade

    configured.db.unlink()
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in ("user_portfolio_grants", "resource_portfolio_grants", "upload_portfolio_grants",
                      "user_portfolio_access", "job_occurrences", "job_runs"):
            conn.exec_driver_sql(f"DROP TABLE {table}")
    engine.dispose()
    _seed(configured.db)
    assert schema_state.inspect_url(settings.database_url).state == schema_state.UNVERSIONED
    assert upgrade(out=lambda line: None) == EXIT_OK
    assert schema_state.inspect_url(settings.database_url).state == schema_state.CURRENT
    with sqlite3.connect(configured.db) as conn:
        assert conn.execute("SELECT user_id, mode, origin FROM user_portfolio_access").fetchall() == [
            ("staff", "all", "legacy_all")]
    assert [a.trigger for a in full_backup.list_archives(configured.data / "backups" / "full")] == ["pre-upgrade"]


def test_the_launcher_runs_the_upgrade_step_and_leaves_an_empty_database_to_the_start(outdated, tmp_path,
                                                                                      monkeypatch):
    from backend import __main__ as launcher

    assert launcher.run_upgrade_step() == 0
    assert schema_state.inspect_url(settings.database_url).state == schema_state.CURRENT
    empty = tmp_path / "fresh.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{empty}")
    assert launcher.run_upgrade_step() == 0
    assert schema_state.inspect_url(settings.database_url).state == schema_state.EMPTY
    assert launcher._pop_data_dir(["--check", "--data-dir", "D:/x"]) == ("D:/x", ["--check"])


def test_the_app_refuses_to_import_on_an_outdated_database_even_with_fallback(outdated):
    env = {**os.environ, "DATABASE_URL": settings.database_url, "SQLITE_PERSISTENT_STORE": "true",
           "ALLOW_INMEMORY_FALLBACK": "true", "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, "-c", "import backend.dependencies"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode != 0
    assert "SchemaUpgradeRequired" in result.stderr and "python -m backend.upgrade" in result.stderr
    assert schema_state.inspect_url(settings.database_url).revision == OLD_REVISION


def test_a_fresh_database_initialised_at_start_matches_the_migrated_schema(tmp_path):
    started, migrated = tmp_path / "started.db", tmp_path / "migrated.db"
    engine = create_engine(f"sqlite:///{started}")
    assert schema_state.ensure_current(engine).state == schema_state.CURRENT
    engine.dispose()
    _migrate(f"sqlite:///{migrated}", "head")

    def columns(db):
        with sqlite3.connect(db) as conn:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {t: {row[1] for row in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}

    assert columns(started) == columns(migrated)
    assert schema_state.inspect_url(f"sqlite:///{started}").revision == schema_state.head_revision()


# --- operations overview API -------------------------------------------------------------------

@pytest.fixture
def api(configured):
    from backend.app import app
    from backend.dependencies import store
    from backend.models import PortfolioCreate

    auth.clear_users()
    store.clear_all()
    portfolio = store.create_portfolio(PortfolioCreate(name="Nord"))

    def bearer(user):
        return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}

    owner = bearer(auth.register_user("ops-owner", "ops-owner@example.test", "Owner", "Secret123", "eigentuemer"))
    restricted = bearer(auth.register_user("ops-staff", "ops-staff@example.test", "Staff", "Secret123", "verwalter",
                                           portfolio_access="selected", portfolio_ids=[portfolio.id]))
    reader = bearer(auth.register_user("ops-reader", "ops-reader@example.test", "Reader", "Secret123", "readonly"))
    yield SimpleNamespace(client=TestClient(app), owner=owner, restricted=restricted, reader=reader)
    auth.clear_users()
    store.clear_all()


def test_restricted_accounts_get_403_on_the_operations_overview(api):
    for headers in (api.restricted, api.reader):
        assert api.client.get("/api/v1/admin/operations", headers=headers).status_code == 403
        assert api.client.post("/api/v1/admin/operations/backup", headers=headers).status_code == 403
        assert api.client.post("/api/v1/admin/operations/restore-probe", headers=headers).status_code == 403
    response = api.client.get("/api/v1/admin/operations", headers=api.owner)
    assert response.status_code == 200
    body = response.json()
    assert {"backup", "restore_probe", "secrets", "warnings", "failures", "jobs", "schema"} <= set(body)
    assert body["backup"]["retention"] == {"daily": 14, "monthly": 6, "pre_upgrade": 3}


def test_the_overview_function_refuses_a_restricted_scope_directly():
    from fastapi import HTTPException

    from backend.routers import operations
    from backend.services.portfolio_scope import AccessScope, scope_context

    with scope_context(AccessScope("u", "verwalter", False, ("p",))):
        with pytest.raises(HTTPException) as refused:
            operations.operations_overview()
    assert refused.value.status_code == 403


def test_manual_backup_and_probe_through_the_api(api):
    from backend import dependencies

    if dependencies._scoped_session is None:
        assert api.client.post("/api/v1/admin/operations/backup", headers=api.owner).status_code == 409
        return
    # SQL mode: database, uploads, settings and key of the configured data directory
    backup = api.client.post("/api/v1/admin/operations/backup", headers=api.owner)
    assert backup.status_code == 200, backup.text
    probe = api.client.post("/api/v1/admin/operations/restore-probe", headers=api.owner)
    assert probe.status_code == 200, probe.text
    assert probe.json()["ok"]
    overview = api.client.get("/api/v1/admin/operations", headers=api.owner).json()
    assert overview["backup"]["last_success"]["archive"] == backup.json()["archive"]
    assert overview["restore_probe"]["last_success"]["archive"] == backup.json()["archive"]
    assert "test-only-password" not in json.dumps(overview)
