"""Synthetic archive/Docker-host failures; no Docker daemon or user data used."""

import gzip
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from scripts import private_server_backup as tool

PASSWORD = "Synthetic backup passphrase 2026"
ENV = ("APP_ORIGIN=https://example.test\nAPP_HOST=example.test\nAPP_HTTP_PORT=8080\n"
       "POSTGRES_USER=immo\nPOSTGRES_DB=immomanager\nPOSTGRES_PASSWORD=" + "a" * 64 +
       "\nJWT_SECRET_KEY=" + "b" * 96 + "\n").encode()
DUMP = b"PGDMP synthetic: owner-hash, TOTP-encrypted-secret, permanent-setup-marker"
COMPOSE = b"services:\n  app:\n    build: .\n  db:\n    image: postgres:16-alpine\n"


def tar_bytes(entries=None, *, format=tarfile.GNU_FORMAT):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=format) as archive:
        if entries is None:
            entries = [(".", None), ("uploads", None), ("uploads/synthetic.txt", b"private synthetic upload")]
        for name, value in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o750 if value is None else 0o600
            info.uid = info.gid = 10001
            if value is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif isinstance(value, tarfile.TarInfo):
                archive.addfile(value)
            else:
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
    return output.getvalue()


class FakeDocker:
    def __init__(self, fixture, compose, env, project, workspace, limits, deadline):
        self.fixture = fixture
        self.project, self.workspace, self.deadline = project, workspace, deadline
        self.base = ["docker", "compose", "--env-file", str(env)]
        self.env_bytes = env.read_bytes()
        fixture.instances.append(self)

    def running(self, service):
        self.fixture.events.append((self.project, "status", service))
        return self.fixture.db_running if service == "db" else self.fixture.app_running.get(self.project, False)

    def require_new_project(self):
        self.fixture.events.append((self.project, "new-project", None))
        if self.fixture.existing_project:
            raise tool.BackupError("Zielprojekt besitzt bereits Container oder Volumes")

    def require_private_volumes(self):
        self.fixture.events.append((self.project, "volume-isolation", None))

    def run(self, args, **kwargs):
        stage = kwargs.get("stage")
        self.fixture.events.append((self.project, stage, list(args)))
        if args[0] == "stop":
            self.fixture.app_running[self.project] = False
        if stage == self.fixture.fail_stage:
            raise tool.BackupError(stage + " fehlgeschlagen")
        if args[-1] == tool.PG_CONNECTIONS:
            return str(self.fixture.writers.pop(0) if self.fixture.writers else 0).encode()
        if args[-1] == tool.PG_DUMP:
            kwargs["output"].write_bytes(DUMP)
        if args[-1] == tool.PG_LIST:
            assert kwargs["input_file"].read_bytes() == DUMP
            return b"synthetic pg_restore table of contents"
        if "-czf-" in args:
            kwargs["output"].write_bytes(self.fixture.tar)
        if args[-1] == tool.PG_RESTORE:
            self.fixture.restored_dump = kwargs["input_file"].read_bytes()
        if "-xzf" in args:
            self.fixture.restored_tar = kwargs["input_file"].read_bytes()
        if stage == "Restaurierte Sitzungen widerrufen":
            assert json.loads(kwargs["input_file"].read_text())["JWT_SECRET_KEY"] == tool._parse_env(self.env_bytes)["JWT_SECRET_KEY"]
            if self.fixture.security_report is not None:
                return self.fixture.security_report
            return json.dumps({"revoked_session_count": 3, "legacy_iban_present": self.fixture.legacy_ibans}).encode()
        if args[0] == "up" and args[-1] == "app":
            self.fixture.app_running[self.project] = True
        if args[0] == "create":
            return b"a" * 64 + b"\n"
        return b""


class DockerFixture:
    def __init__(self):
        self.events, self.instances = [], []
        self.app_running = {"original": True}
        self.db_running = True
        self.fail_stage = None
        self.existing_project = False
        self.tar = tar_bytes()
        self.writers = []
        self.restored_dump = self.restored_tar = None
        self.legacy_ibans = False
        self.security_report = None

    def __call__(self, *args):
        return FakeDocker(self, *args)

    def stages(self, project="original"):
        return [stage for target, stage, _ in self.events if target == project]


@pytest.fixture
def installation(tmp_path):
    # On Windows this performs and verifies actual SID/System/Admin ACLs. No
    # ambient or user-owned .env is read/changed by these tests.
    with tool.private_workspace(tmp_path) as (directory, sid):
        env, compose = directory / "synthetic.env", directory / "synthetic-compose.yml"
        with tool._new_file(env) as output:
            output.write(ENV)
        tool._verify_private(env, directory, sid, protected=False)
        compose.write_bytes(COMPOSE)
        yield directory, env, compose


def save(installation, docker=None, **kwargs):
    directory, env, compose = installation
    factory = docker or DockerFixture()
    destination = directory / "complete.immoenc"
    result = tool.backup(project="original", destination=destination, compose_file=compose,
                         env_file=env, password=PASSWORD, docker_factory=factory, **kwargs)
    return destination, result, factory


def load(installation, source, docker=None, **kwargs):
    directory, _, compose = installation
    factory = docker or DockerFixture()
    result = tool.restore(project="restored", source=source, compose_file=compose,
                          env_output=directory / "restored.env", password=PASSWORD, docker_factory=factory, **kwargs)
    return result, factory


def test_encrypted_roundtrip_stops_writers_resumes_original_and_starts_after_both_restores(installation):
    docker = DockerFixture()
    docker.writers = [2, 0]
    source, result, docker = save(installation, docker)
    assert result["encrypted"] is True and source.read_bytes().startswith(tool.MAGIC)
    assert DUMP not in source.read_bytes() and ENV not in source.read_bytes()
    stages = docker.stages()
    assert stages.index("App anhalten") < stages.index("Datenbank-Ruhezustand") < stages.index("PostgreSQL-Sicherung")
    assert stages.index("Appdaten-Sicherung") < stages.index("App wieder starten")
    assert stages.count("Datenbank-Ruhezustand") == 2
    restored, _ = load(installation, source, docker)
    assert restored["project"] == "restored"
    assert docker.restored_dump == DUMP and docker.restored_tar == docker.tar
    restored_env = tool._parse_env((installation[0] / "restored.env").read_bytes())
    original_env = tool._parse_env(ENV)
    assert restored_env["JWT_SECRET_KEY"] != original_env["JWT_SECRET_KEY"]
    assert {k: v for k, v in restored_env.items() if k != "JWT_SECRET_KEY"} == {k: v for k, v in original_env.items() if k != "JWT_SECRET_KEY"}
    assert restored["sessions_revoked"] == 3 and restored["signing_key_rotated"] is True
    stages = docker.stages("restored")
    assert stages.index("new-project") < stages.index("Serverimage bauen") < stages.index("Neues Projekt reservieren")
    assert stages.index("PostgreSQL-Wiederherstellung") < stages.index("Appdaten-Wiederherstellung") < stages.index("Wiederhergestellte App starten")
    assert stages.index("Appdaten-Wiederherstellung") < stages.index("Restaurierte Sitzungen widerrufen") < stages.index("Wiederhergestellte App starten")
    assert stages[-2:] == ["status", "Eigene leere Projektreservierung freigeben"]
    restore_args = next(args for target, stage, args in docker.events if stage == "PostgreSQL-Wiederherstellung")
    assert "--exit-on-error" in restore_args[-1] and "--no-owner" in restore_args[-1] and "--no-privileges" in restore_args[-1]


def test_large_contract_workspace_budgets_survive_encrypted_server_restore(installation):
    configured = ENV + b"CONTRACT_WORKSPACE_PAGE_MAX_SIZE=6000\nCONTRACT_WORKSPACE_SEARCH_MAX_CHARS=12000\n"
    installation[1].write_bytes(configured)
    source, _, docker = save(installation)
    assert configured not in source.read_bytes()
    load(installation, source, docker)
    restored = tool._parse_env((installation[0] / "restored.env").read_bytes())
    assert restored["CONTRACT_WORKSPACE_PAGE_MAX_SIZE"] == "6000"
    assert restored["CONTRACT_WORKSPACE_SEARCH_MAX_CHARS"] == "12000"


@pytest.mark.parametrize("name", sorted(tool.CONTRACT_WORKSPACE_ENV_KEYS))
@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true", ""])
def test_invalid_contract_workspace_budget_blocks_backup_before_docker(installation, name, value):
    installation[1].write_bytes(ENV + f"{name}={value}\n".encode())
    docker = DockerFixture()
    with pytest.raises(tool.BackupError):
        save(installation, docker)
    assert not docker.instances
    assert not (installation[0] / "complete.immoenc").exists()


@pytest.mark.parametrize("stage", ["App anhalten", "Datenbank-Ruhezustand", "PostgreSQL-Sicherung", "PostgreSQL-Dumpprüfung", "Appdaten-Sicherung"])
def test_every_offline_failure_resumes_previously_running_app_and_publishes_nothing(installation, stage):
    docker = DockerFixture()
    docker.fail_stage = stage
    with pytest.raises(tool.BackupError, match="fehlgeschlagen"):
        save(installation, docker)
    assert "App wieder starten" in docker.stages()
    assert docker.app_running["original"]
    assert not (installation[0] / "complete.immoenc").exists()
    assert not list(installation[0].glob("*.partial"))


def test_stopped_app_stays_stopped_on_success_and_failure(installation):
    docker = DockerFixture()
    docker.app_running["original"] = False
    save(installation, docker)
    assert "App anhalten" not in docker.stages() and "App wieder starten" not in docker.stages()
    assert not docker.app_running["original"]
    (installation[0] / "complete.immoenc").unlink()
    docker.fail_stage = "PostgreSQL-Sicherung"
    with pytest.raises(tool.BackupError):
        save(installation, docker)
    assert "App wieder starten" not in docker.stages()


def test_resume_failure_does_not_claim_success_even_after_valid_package(installation):
    docker = DockerFixture()
    docker.fail_stage = "App wieder starten"
    with pytest.raises(tool.BackupError, match="manuell"):
        save(installation, docker)
    assert (installation[0] / "complete.immoenc").is_file()


def test_backup_refuses_missing_db_or_existing_destination_before_stopping(installation):
    docker = DockerFixture()
    docker.db_running = False
    with pytest.raises(tool.BackupError, match="PostgreSQL-Container"):
        save(installation, docker)
    assert "App anhalten" not in docker.stages()
    destination = installation[0] / "complete.immoenc"
    destination.write_bytes(b"valid older backup")
    docker = DockerFixture()
    with pytest.raises(tool.BackupError, match="existiert"):
        save(installation, docker)
    assert not docker.events and destination.read_bytes() == b"valid older backup"


def test_atomic_publication_refuses_destination_created_after_preflight(installation):
    partial, destination = installation[0] / "owned.partial", installation[0] / "existing.enc"
    partial.write_bytes(b"new encrypted package")
    destination.write_bytes(b"existing encrypted package")
    with pytest.raises(FileExistsError):
        tool._publish_new(partial, destination)
    assert destination.read_bytes() == b"existing encrypted package"
    assert partial.read_bytes() == b"new encrypted package"


@pytest.mark.parametrize("failure", ["wrong-password", "ciphertext", "truncated"])
def test_authentication_failures_do_not_call_docker_or_create_config(installation, failure):
    source, _, _ = save(installation)
    password = PASSWORD
    if failure == "wrong-password":
        password = "Another synthetic passphrase"
    else:
        data = bytearray(source.read_bytes())
        if failure == "ciphertext":
            data[tool.HEADER_SIZE + 10] ^= 1
        else:
            data = data[:20]
        source.write_bytes(data)
    docker = DockerFixture()
    with pytest.raises(tool.BackupError):
        tool.restore(project="restored", source=source, compose_file=installation[2], env_output=installation[0] / "restored.env",
                     password=password, docker_factory=docker)
    assert not docker.events and not (installation[0] / "restored.env").exists()


@pytest.mark.parametrize("stage", ["Serverimage bauen", "Neues Projekt reservieren", "Neue PostgreSQL-Instanz starten",
                                  "PostgreSQL-Wiederherstellung", "Appdaten-Wiederherstellung", "Restaurierte Sitzungen widerrufen"])
def test_failed_restore_keeps_new_config_for_inspection_and_never_starts_app(installation, stage):
    source, _, _ = save(installation)
    docker = DockerFixture()
    docker.fail_stage = stage
    with pytest.raises(tool.BackupError, match="fehlgeschlagen"):
        load(installation, source, docker)
    assert tool._parse_env((installation[0] / "restored.env").read_bytes())["JWT_SECRET_KEY"] != tool._parse_env(ENV)["JWT_SECRET_KEY"]
    assert "Wiederhergestellte App starten" not in docker.stages("restored")
    assert "Eigene leere Projektreservierung freigeben" not in docker.stages("restored")
    assert not any(args and args[0] in {"down", "rm"} for _, _, args in docker.events)


def test_existing_project_original_name_or_changed_compose_refused_before_mutations(installation):
    source, _, _ = save(installation)
    docker = DockerFixture()
    docker.existing_project = True
    with pytest.raises(tool.BackupError, match="Zielprojekt"):
        load(installation, source, docker)
    assert docker.stages("restored") == ["new-project"]
    assert not (installation[0] / "restored.env").exists()
    docker = DockerFixture()
    with pytest.raises(tool.BackupError, match="neuen Projektnamen"):
        tool.restore(project="original", source=source, compose_file=installation[2], env_output=installation[0] / "restored.env",
                     password=PASSWORD, docker_factory=docker)
    assert not docker.events
    installation[2].write_bytes(COMPOSE + b"# altered deployment\n")
    with pytest.raises(tool.BackupError, match="Compose-Profil"):
        load(installation, source, docker)
    assert not docker.events


@pytest.mark.parametrize("report", [b"{}", b"[]", b"not-json", b'{"revoked_session_count":true,"legacy_iban_present":false}',
    b'{"revoked_session_count":-1,"legacy_iban_present":false}', b'{"revoked_session_count":1,"legacy_iban_present":"true"}'])
def test_unconfirmed_offline_security_result_never_starts_restored_app(installation, report):
    source, _, _ = save(installation)
    docker = DockerFixture()
    docker.security_report = report
    with pytest.raises(tool.BackupError):
        load(installation, source, docker)
    assert "Wiederhergestellte App starten" not in docker.stages("restored")
    assert not docker.app_running.get("restored", False)
    assert tool._parse_env((installation[0] / "restored.env").read_bytes())["JWT_SECRET_KEY"] != tool._parse_env(ENV)["JWT_SECRET_KEY"]


def test_actual_legacy_flag_keeps_original_signer_only_in_protected_decryption_ring(installation):
    source, _, _ = save(installation)
    docker = DockerFixture()
    docker.legacy_ibans = True
    load(installation, source, docker)
    target = installation[0] / "restored.env"
    values = tool._parse_env(target.read_bytes())
    original_signer = tool._parse_env(ENV)["JWT_SECRET_KEY"]
    assert values["JWT_SECRET_KEY"] != original_signer
    assert json.loads(values["ENCRYPTION_LEGACY_JWT_KEYS"]) == [original_signer]
    with tool.private_workspace() as (audit, sid):
        tool._verify_private(target, audit, sid)
    assert not list(installation[0].glob(".restored.env.*.tmp"))


def encrypted_candidate(installation, *, mutations=None, extra=False):
    directory, _, compose = installation
    data = {"database.dump": DUMP, "appdata.tar.gz": tar_bytes(), "server.env": ENV}
    deadline = tool.Deadline(60)
    manifest = {"format": "immomanager-private-server", "version": 1, "source_project": "original", "created_utc": "2026-10-01T08:00:00+00:00",
                "postgres_major": 16, "origin": "https://example.test", "compose_sha256": tool._digest(compose, 65536, deadline)["sha256"],
                "files": {name: {"size_bytes": len(value), "sha256": tool.hashlib.sha256(value).hexdigest()} for name, value in data.items()}}
    if mutations:
        mutations(data, manifest)
    source = directory / "candidate.immoenc"
    with tool.encrypted_zip(source, PASSWORD) as archive:
        for name, value in data.items():
            archive.writestr(name, value)
        archive.writestr("manifest.json", json.dumps(manifest))
        if extra:
            archive.writestr("unexpected.txt", "not allowed")
    return source


@pytest.mark.parametrize("problem", ["checksum", "size-bool", "scope", "origin", "env-unknown", "extra", "tar-traversal", "dump-magic"])
def test_authenticated_but_invalid_payload_rejected_before_docker(installation, problem):
    def mutate(data, manifest):
        if problem == "checksum":
            data["database.dump"] += b"tampered"
        elif problem == "size-bool":
            manifest["files"]["database.dump"]["size_bytes"] = True
        elif problem == "scope":
            manifest["format"] = "business-data-only"
        elif problem == "origin":
            manifest["origin"] = "https://foreign.test"
        elif problem == "env-unknown":
            data["server.env"] += b"DATABASE_URL=foreign\n"
        elif problem == "tar-traversal":
            data["appdata.tar.gz"] = tar_bytes([("../outside", b"evil")])
        elif problem == "dump-magic":
            data["database.dump"] = b"SQL plaintext instead of custom archive"
        if problem in {"env-unknown", "tar-traversal", "dump-magic"}:
            name = "server.env" if problem == "env-unknown" else "appdata.tar.gz" if problem == "tar-traversal" else "database.dump"
            manifest["files"][name] = {"size_bytes": len(data[name]), "sha256": tool.hashlib.sha256(data[name]).hexdigest()}
    source = encrypted_candidate(installation, mutations=mutate, extra=problem == "extra")
    docker = DockerFixture()
    with pytest.raises((tool.BackupError, ValueError)):
        load(installation, source, docker)
    assert not docker.events and not (installation[0] / "restored.env").exists()


@pytest.mark.parametrize("format", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT, tarfile.USTAR_FORMAT])
def test_legitimate_tar_formats_and_long_names_are_streamed(installation, format):
    path = installation[0] / "valid.tar.gz"
    name = "uploads/" + ("long-name/" * 15 if format != tarfile.USTAR_FORMAT else "") + "synthetic.txt"
    path.write_bytes(tar_bytes([(".", None), (name, b"synthetic")], format=format))
    tool.check_tar(path, tool.Limits(), tool.Deadline(60))


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE, tarfile.GNUTYPE_SPARSE])
def test_tar_special_entries_rejected_without_extraction(installation, kind):
    info = tarfile.TarInfo("uploads/evil")
    info.type, info.linkname = kind, "../../outside"
    path = installation[0] / "bad.tar.gz"
    path.write_bytes(tar_bytes([("ignored", info)]))
    with pytest.raises(tool.BackupError, match="Spezialdateien"):
        tool.check_tar(path, tool.Limits(), tool.Deadline(60))


@pytest.mark.parametrize("entries", [ [("/absolute", b"a")], [("uploads/../outside", b"a")], [("C:\\outside", b"a")],
                                      [("uploads/a", b"a"), ("uploads/a", b"b")],
                                      [("uploads/a", b"a"), ("uploads/a/b", b"b")],
                                      [("uploads/a/b", b"a"), ("uploads/a", b"b")] ])
def test_tar_path_and_duplicate_type_attacks_rejected(installation, entries):
    path = installation[0] / "bad.tar.gz"
    path.write_bytes(tar_bytes(entries))
    with pytest.raises(tool.BackupError):
        tool.check_tar(path, tool.Limits(), tool.Deadline(60))


def test_tar_entry_expansion_metadata_and_crc_budgets(installation):
    path = installation[0] / "limited.tar.gz"
    path.write_bytes(tar_bytes([("a", b"1234"), ("b", b"5678")]))
    with pytest.raises(tool.BackupError, match="viele Einträge"):
        tool.check_tar(path, tool.Limits(entries=1), tool.Deadline(60))
    with pytest.raises(tool.BackupError, match="Entpackte Appdaten"):
        tool.check_tar(path, tool.Limits(expanded_data_bytes=4), tool.Deadline(60))
    path.write_bytes(tar_bytes([("a/" * 100, b"b")]))
    with pytest.raises(tool.BackupError, match="Metadaten"):
        tool.check_tar(path, tool.Limits(small_bytes=100), tool.Deadline(60))
    corrupted = bytearray(tar_bytes())
    corrupted[-5] ^= 1
    path.write_bytes(corrupted)
    with pytest.raises(tool.BackupError, match="beschädigt"):
        tool.check_tar(path, tool.Limits(), tool.Deadline(60))


def test_tar_checksum_end_marker_and_timeout(installation):
    path = installation[0] / "bad.tar.gz"
    raw = bytearray(gzip.decompress(tar_bytes()))
    raw[0] ^= 1
    path.write_bytes(gzip.compress(raw))
    with pytest.raises(tool.BackupError, match="Headerprüfsumme"):
        tool.check_tar(path, tool.Limits(), tool.Deadline(60))
    path.write_bytes(gzip.compress(gzip.decompress(tar_bytes())[:512]))
    with pytest.raises(tool.BackupError, match="unvollständig|Endmarkierung"):
        tool.check_tar(path, tool.Limits(), tool.Deadline(60))
    path.write_bytes(tar_bytes())
    deadline = tool.Deadline(60)
    deadline.end = time.monotonic() - 1
    with pytest.raises(tool.BackupError, match="Zeitlimit"):
        tool.check_tar(path, tool.Limits(), deadline)


def test_docker_argv_env_isolation_and_unlabelled_project_volume_refusal(installation, monkeypatch):
    directory, env, compose = installation
    monkeypatch.setenv("POSTGRES_PASSWORD", "foreign-secret")
    monkeypatch.setenv("JWT_SECRET_KEY", "foreign-jwt")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "foreign-project")
    docker = tool.Docker(compose, env, "restored", directory, tool.Limits(), tool.Deadline(60))
    assert "POSTGRES_PASSWORD" not in docker.environment and "COMPOSE_PROJECT_NAME" not in docker.environment
    assert docker.base[-1] == str(env)
    assert docker.base[docker.base.index("--project-directory") + 1] == str(compose.parent)
    captured = []
    def run(args, **kwargs):
        captured.append(args)
        return b"restored_appdata\n" if args == ["volume", "ls", "--format", "{{.Name}}"] else b""
    monkeypatch.setattr(docker, "run", run)
    with pytest.raises(tool.BackupError, match="Zielprojekt"):
        docker.require_new_project()
    assert len(captured) == 4 and not any(args[0] in {"up", "rm", "down"} for args in captured)


def test_compose_fingerprint_portable_between_windows_and_linux_line_endings(installation):
    compose = installation[2]
    before = tool._compose_digest(compose, tool.Limits(), tool.Deadline(60))
    compose.write_bytes(COMPOSE.replace(b"\n", b"\r\n"))
    assert tool._compose_digest(compose, tool.Limits(), tool.Deadline(60)) == before


@pytest.mark.parametrize("resource", ["label-container", "name-container", "label-volume"])
def test_project_probe_checks_stopped_containers_names_and_volume_labels(installation, monkeypatch, resource):
    directory, env, compose = installation
    docker = tool.Docker(compose, env, "restored", directory, tool.Limits(), tool.Deadline(60))
    def run(args, **kwargs):
        if resource == "label-container" and args[:2] == ["ps", "-a"] and "--filter" in args:
            return b"abcdef123456\n"
        if resource == "name-container" and args == ["ps", "-a", "--format", "{{.Names}}"]:
            return b"restored-db-1\n"
        if resource == "label-volume" and args[:2] == ["volume", "ls"] and "--filter" in args:
            return b"custom_labelled_volume\n"
        return b""
    monkeypatch.setattr(docker, "run", run)
    with pytest.raises(tool.BackupError, match="Zielprojekt"):
        docker.require_new_project()


@pytest.mark.parametrize("attack", [None, "external", "foreign-name", "bind", "driver-options", "extra-service"])
def test_resolved_compose_cannot_restore_to_external_or_foreign_data(installation, monkeypatch, attack):
    directory, env, compose = installation
    docker = tool.Docker(compose, env, "restored", directory, tool.Limits(), tool.Deadline(60))
    config = {"volumes": {"appdata": {"name": "restored_appdata"}, "pgdata": {"name": "restored_pgdata"}},
              "services": {"app": {"volumes": [{"type": "volume", "source": "appdata", "target": "/data"}]},
                           "db": {"volumes": [{"type": "volume", "source": "pgdata", "target": "/var/lib/postgresql/data"}]}}}
    if attack == "external":
        config["volumes"]["appdata"]["external"] = True
    elif attack == "foreign-name":
        config["volumes"]["pgdata"]["name"] = "original_pgdata"
    elif attack == "bind":
        config["services"]["app"]["volumes"][0]["type"] = "bind"
    elif attack == "driver-options":
        config["volumes"]["appdata"]["driver_opts"] = {"type": "none", "device": "/existing/private/data", "o": "bind"}
    elif attack == "extra-service":
        config["services"]["other-writer"] = {}
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return json.dumps(config).encode()
    monkeypatch.setattr(docker, "run", run)
    if attack:
        with pytest.raises(tool.BackupError):
            docker.require_private_volumes()
    else:
        docker.require_private_volumes()
    assert calls == [["config", "--format", "json"]]


def test_real_subprocess_budget_timeout_and_nonzero_never_echo_stderr(installation, capsys):
    directory, env, compose = installation
    docker = tool.Docker(compose, env, "restored", directory, tool.Limits(), tool.Deadline(60))
    docker.base = [sys.executable, "-c", "import sys;sys.stderr.write('SYNTHETIC-SECRET');sys.exit(8)"]
    with pytest.raises(tool.BackupError, match="fehlgeschlagen"):
        docker.run([], stage="Synthetic subprocess")
    docker.base = [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*2048)"]
    output = directory / "bounded-binary-output"
    with pytest.raises(tool.BackupError):
        docker.run([], maximum=1024, output=output)
    assert output.stat().st_size <= 1024
    docker.base = [sys.executable, "-c", "import time;time.sleep(5)"]
    docker.deadline = tool.Deadline(0.15)
    before = time.monotonic()
    with pytest.raises(tool.BackupError, match="Zeitlimit"):
        docker.run([])
    assert time.monotonic() - before < 3
    assert "SYNTHETIC-SECRET" not in capsys.readouterr().err


def test_cli_rejects_misplaced_secret_argument_without_echoing_it():
    process = subprocess.run([sys.executable, str(Path(tool.__file__)), "backup", "--project", "original",
                              "--destination", "synthetic.enc", "--password", "SYNTHETIC-MISPLACED-SECRET"],
                             capture_output=True, timeout=20, check=False)
    assert process.returncode == 2
    assert b"SYNTHETIC-MISPLACED-SECRET" not in process.stdout + process.stderr


def test_cli_wrong_password_before_docker_and_no_secrets_in_output(installation):
    source = encrypted_candidate(installation)
    process = subprocess.run([sys.executable, str(Path(tool.__file__)), "restore", "--project", "restored", "--source", str(source),
                              "--compose-file", str(installation[2]), "--env-output", str(installation[0] / "restored.env"), "--password-stdin"],
                             input=b"Wrong synthetic passphrase\n", capture_output=True, timeout=20, check=False)
    assert process.returncode == 1
    assert b"Passphrase falsch" in process.stderr
    assert b"Wrong synthetic passphrase" not in process.stdout + process.stderr
    assert not (installation[0] / "restored.env").exists()


def test_getpass_echo_fallback_refused_and_password_limits(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    def echoed(prompt):
        import warnings
        warnings.warn("fallback", getpass.GetPassWarning)
        pytest.fail("fallback input must not continue")
    import getpass
    monkeypatch.setattr(getpass, "getpass", echoed)
    with pytest.raises(getpass.GetPassWarning):
        tool._read_password(False, confirm=True)
    for password in ("short", "x" * 1025):
        with pytest.raises(tool.BackupError):
            tool._password(password)


def test_permissions_and_workspace_cleanup_are_actual_platform_checks(tmp_path):
    with tool.private_workspace(tmp_path) as (directory, sid):
        owned = directory
        file = directory / "synthetic-secret.env"
        with tool._new_file(file) as output:
            tool._protect(file, directory, sid)
            output.write(ENV)
        tool._verify_private(file, directory, sid)
        if os.name != "nt":
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
        else:
            # Change only our NEW synthetic file, prove broader ACL is rejected.
            tool._acl_command(["icacls", str(file), "/grant", "*S-1-1-0:R"])
            with pytest.raises(tool.BackupError, match="weitere Identitäten"):
                tool._verify_private(file, directory, sid)
    assert not owned.exists()


def test_public_protected_new_file_is_private_before_secrets_and_preserves_existing_file(tmp_path):
    path = tmp_path / "new-server.env"
    with tool.protected_new_file(path) as output:
        assert path.stat().st_size == 0
        with tool.private_workspace() as (audit, sid):
            tool._verify_private(path, audit, sid)
        output.write(ENV)
    assert path.read_bytes() == ENV
    with pytest.raises(tool.BackupError, match="existiert"):
        with tool.protected_new_file(path):
            pytest.fail("Existing file must never be opened")
    assert path.read_bytes() == ENV


def test_public_protected_new_file_removes_only_its_own_file_on_failure(tmp_path):
    path = tmp_path / "failed-new-server.env"
    with pytest.raises(RuntimeError, match="synthetic"):
        with tool.protected_new_file(path) as output:
            output.write(b"synthetic secret")
            raise RuntimeError("synthetic")
    assert not path.exists()


def test_tar_path_memory_budget_for_many_deep_names(installation):
    path = installation[0] / "deep.tar.gz"
    path.write_bytes(tar_bytes([("one/two/three/four/five/synthetic", b"a")]))
    with pytest.raises(tool.BackupError, match="Pfadmetadaten"):
        tool.check_tar(path, tool.Limits(metadata_bytes=50), tool.Deadline(60))


def test_sddl_rejects_foreign_or_unprotected_permissions():
    sid = "S-1-5-21-1-2-3-1001"
    valid = "D:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;FA;;;" + sid + ")"
    tool._verify_sddl(valid, sid, protected=True)
    for invalid in (valid + "(A;;FR;;;WD)", valid.replace("D:PAI", "D:AI"), valid.replace(";;;" + sid, ";;;BU")):
        with pytest.raises(tool.BackupError):
            tool._verify_sddl(invalid, sid, protected=True)


def test_symlink_destination_refused_before_docker(installation):
    target = installation[0] / "real-file"
    target.write_bytes(b"do not change")
    destination = installation[0] / "complete.immoenc"
    try:
        destination.symlink_to(target)
    except OSError:
        pytest.skip("This host does not allow symlink creation")
    docker = DockerFixture()
    with pytest.raises(tool.BackupError, match="Symlink"):
        save(installation, docker)
    assert not docker.events and target.read_bytes() == b"do not change"
