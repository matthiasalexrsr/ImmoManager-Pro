"""Durable lifecycle bridge for the existing private server backup service."""

from pathlib import Path

from scripts.private_server_backup import (
    Deadline,
    Docker,
    _compose_digest,
    _digest,
    _new_file,
    _parse_env,
    _read_file,
    _safe_path,
    _verify_private,
    backup,
    private_workspace,
)

from .plan import BackupOperationError


def server_backup(plan, journal, run, password, limits):
    document = run["document"]
    from .plan import Installation
    from .runner import digest, remember_archive
    installation = Installation.model_validate(document["installation"])

    def lifecycle(stage, receipt):
        document["phase"] = stage
        if stage == "prepared" and receipt["was_running"]:
            if not receipt["app_containers"]:
                raise BackupOperationError("managed_server_container_required")
            document["resume"] = receipt
        elif stage == "published":
            remember_archive(document)
        elif stage == "resumed":
            document.pop("resume", None)
        journal.save(run)

    document["backup_report"] = backup(project=installation.project, destination=Path(document["archive"]),
        compose_file=installation.compose_file, env_file=installation.env_file, password=password, limits=limits,
        lifecycle=lifecycle)
    document["digest"] = digest(Path(document["archive"]))
    journal.save(run)


def resume_server(installation, receipt, limits):
    if receipt.get("project") != installation.project or receipt.get("was_running") is not True:
        raise BackupOperationError("managed_server_receipt_invalid")
    deadline = Deadline(min(120, limits.timeout_seconds))
    compose, env = _safe_path(installation.compose_file), _safe_path(installation.env_file)
    with private_workspace() as (workspace, sid):
        _verify_private(env, workspace, sid, protected=False)
        if (_compose_digest(compose, limits, deadline) != receipt.get("compose_sha256")
                or _digest(env, limits.small_bytes, deadline) != receipt.get("env_fingerprint")):
            raise BackupOperationError("managed_server_configuration_changed")
        values = _read_file(env, limits.small_bytes, deadline)
        _parse_env(values)
        with _new_file(workspace / "server.env") as output:
            output.write(values)
        docker = Docker(compose, workspace / "server.env", installation.project, workspace, limits, deadline)
        if docker.compose_digest != receipt["compose_sha256"]:
            raise BackupOperationError("managed_server_configuration_changed")
        docker.require_private_volumes()
        if docker.app_identity() != receipt.get("app_containers"):
            raise BackupOperationError("managed_server_container_changed")
        # --wait completes only after the actual application healthcheck passes.
        docker.run(["up", "-d", "--no-deps", "--wait", "--wait-timeout", "90", "app"], stage="App wieder starten")
        if not docker.running("app"):
            raise BackupOperationError("managed_server_restart_failed")
