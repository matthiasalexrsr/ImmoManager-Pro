"""CLI subprocesses use only synthetic, pre-migrated SQLite databases."""

import os
import subprocess
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.app import app
from backend.db.auth_models import AuthSetupORM
from backend.db.orm_models import Base, PortfolioORM, UserORM
from scripts import server_admin

PASSWORD = "a synthetic private passphrase"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli_database(tmp_path):
    database = tmp_path / "private server with spaces.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    yield database, engine
    engine.dispose()


def run_cli(database, index=0, password=PASSWORD, extra_env=None):
    return subprocess.run([
        sys.executable, str(ROOT / "scripts" / "server_admin.py"), "initial-owner", "--username", f"owner{index}",
        "--email", f"owner{index}@example.com", "--full-name", "Synthetic Owner", "--password-stdin",
    ], input=password + "\n", text=True, capture_output=True, timeout=30, cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}", "ENVIRONMENT": "development",
             "SQLITE_PERSISTENT_STORE": "false", "ALLOW_INMEMORY_FALLBACK": "true", "AUTO_SEED_DEMO_DATA": "true",
             "PYTHONUTF8": "1", **(extra_env or {})})


def test_cli_bootstrap_persists_hashed_owner_supports_login_and_does_not_seed_or_fallback(cli_database, monkeypatch):
    database, engine = cli_database
    result = run_cli(database)
    assert result.returncode == 0, result.stderr
    assert PASSWORD not in result.stdout + result.stderr
    factory = sessionmaker(bind=engine)
    with factory() as session:
        owner = session.scalar(select(UserORM))
        assert owner.role == "eigentuemer" and owner.is_active
        assert owner.hashed_password != PASSWORD and auth.verify_password(PASSWORD, owner.hashed_password)
        assert session.scalar(select(func.count()).select_from(AuthSetupORM)) == 1
        assert session.scalar(select(func.count()).select_from(PortfolioORM)) == 0
        assert owner.hashed_password not in result.stdout + result.stderr
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "owner0", "password": PASSWORD})
        assert login.status_code == 200
        assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + login.json()["access_token"]}).json()["role"] == "eigentuemer"


def test_duplicate_cli_refuses_a_second_owner_without_secrets(cli_database):
    database, engine = cli_database
    assert run_cli(database).returncode == 0
    duplicate = run_cli(database, 1)
    assert duplicate.returncode == 1
    assert "bereits abgeschlossen" in duplicate.stderr
    assert PASSWORD not in duplicate.stdout + duplicate.stderr
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(UserORM)) == 1


def test_independent_cli_processes_contend_on_the_permanent_setup_marker(cli_database):
    database, engine = cli_database
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda index: run_cli(database, index), [0, 1]))
    assert sorted(result.returncode for result in results) == [0, 1]
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(UserORM)) == 1
        assert session.scalar(select(func.count()).select_from(AuthSetupORM)) == 1
    assert all(PASSWORD not in result.stdout + result.stderr for result in results)


@pytest.mark.parametrize("password", ["Strong123", "", "x" * 1025])
def test_cli_rejects_short_empty_or_overlong_secret_without_echoing_it(cli_database, password):
    database, engine = cli_database
    result = run_cli(database, password=password)
    assert result.returncode == 1
    if password:
        assert password not in result.stdout + result.stderr
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(UserORM)) == 0


def test_cli_missing_sqlite_path_is_not_created_even_when_fallback_enabled(tmp_path):
    database = tmp_path / "missing.db"
    result = run_cli(database)
    assert result.returncode == 1
    assert not database.exists()
    assert PASSWORD not in result.stdout + result.stderr


def test_cli_missing_schema_and_invalid_user_data_fail_closed(cli_database, tmp_path):
    database = tmp_path / "unmigrated.db"
    database.touch()
    assert run_cli(database).returncode == 1
    existing, engine = cli_database
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "server_admin.py"), "initial-owner", "--username", "new", "--email", "invalid", "--full-name", "Synthetic", "--password-stdin"], input=PASSWORD + "\n", text=True, capture_output=True, timeout=30, cwd=ROOT, env={**os.environ, "DATABASE_URL": f"sqlite:///{existing.as_posix()}", "PYTHONUTF8": "1"})
    assert result.returncode == 1
    assert PASSWORD not in result.stdout + result.stderr
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(UserORM)) == 0


def test_cli_interactive_password_uses_getpass_twice_and_never_echoes(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    prompts = []
    monkeypatch.setattr(server_admin.getpass, "getpass", lambda prompt: prompts.append(prompt) or PASSWORD)
    recorded = []
    monkeypatch.setattr(server_admin, "bootstrap_owner", lambda *args: recorded.append(args))
    assert server_admin.main(["initial-owner", "--username", "owner", "--email", "owner@example.com", "--full-name", "Synthetic"]) == 0
    assert len(prompts) == 2 and recorded[0][-1] == PASSWORD
    assert PASSWORD not in capsys.readouterr().out


def test_cli_database_exception_does_not_print_connection_credentials(monkeypatch, capsys):
    monkeypatch.setattr(server_admin, "_read_password", lambda from_stdin: PASSWORD)
    def fail(*args):
        raise RuntimeError("postgresql://synthetic:SECRET@invalid/private")
    monkeypatch.setattr(server_admin, "bootstrap_owner", fail)
    assert server_admin.main(["initial-owner", "--username", "owner", "--email", "owner@example.com", "--full-name", "Synthetic"]) == 1
    output = capsys.readouterr()
    assert "SECRET" not in output.out + output.err
    assert PASSWORD not in output.out + output.err


def test_cli_refuses_getpass_echo_fallback_instead_of_reading_plaintext(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    def unsupported_terminal(prompt):
        warnings.warn("Cannot disable echo", server_admin.getpass.GetPassWarning, stacklevel=1)
        pytest.fail("Echo fallback must be stopped before reading")
    monkeypatch.setattr(server_admin.getpass, "getpass", unsupported_terminal)
    monkeypatch.setattr(server_admin, "bootstrap_owner", lambda *args: pytest.fail("Must not create an owner"))
    assert server_admin.main(["initial-owner", "--username", "owner", "--email", "owner@example.com", "--full-name", "Synthetic"]) == 1
    assert PASSWORD not in capsys.readouterr().err


def test_cli_rejects_password_arguments_without_echoing_the_misplaced_secret(capsys):
    with pytest.raises(SystemExit) as error:
        server_admin.main(["initial-owner", "--username", "owner", "--email", "owner@example.com", "--full-name", "Synthetic", "--password", PASSWORD])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err
