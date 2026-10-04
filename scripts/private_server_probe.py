"""Portless disposable restore. Only explicit offline commands can run the app image."""

import json
import re
import secrets
from pathlib import Path
from uuid import uuid4

from scripts.private_server_backup import (
    PG_RESTORE,
    BackupError,
    Deadline,
    Docker,
    Limits,
    _compose_digest,
    _json,
    _new_file,
    _parse_env,
    _read_file,
    _safe_path,
    private_workspace,
    verify_package,
)

OWNER_LABEL = "immomanager.restore.probe"


def _profile(config, project, token, original):
    """Derive solely after the unchanged archived source profile was authenticated."""
    from backend.services.recovery_sessions import rotated_configuration
    services = config["services"]
    app = services["app"]
    build = app.get("build")
    if not isinstance(build, dict) or set(build) - {"context", "dockerfile", "args", "labels"}:
        raise BackupError("Probe benötigt einen einfachen lokalen Serverbuild.")
    build = {**build, "labels": {OWNER_LABEL: token}}
    restored = rotated_configuration(original)
    restored.update(POSTGRES_PASSWORD=secrets.token_hex(32), APP_ORIGIN="https://isolated.invalid", APP_HOST="isolated.invalid")
    # No ambient connector or original network credential is carried over.
    environment = {"ENVIRONMENT": "production"}
    environment.update({key: value for key, value in restored.items() if key.startswith("ENCRYPTION_")})
    environment.update(DATABASE_URL=f"postgresql://{restored['POSTGRES_USER']}:{restored['POSTGRES_PASSWORD']}@db:5432/{restored['POSTGRES_DB']}",
        JWT_SECRET_KEY=restored["JWT_SECRET_KEY"], CORS_ORIGINS="https://isolated.invalid", TRUSTED_HOSTS="isolated.invalid",
        OPERATIONAL_SCHEDULER_ENABLED="false", AI_ENABLED="false", PLUGIN_DIRS="[]", AUTO_MIGRATE="false",
        AUTO_SEED_DEMO_DATA="false", DATA_DIR="/data", UPLOADS_DIR="/data/uploads", INTEGRATION_STATE_FILE="/data/integrations.json")
    labels = {OWNER_LABEL: token}
    profile = {"services": {
        "app": {"build": build, "image": project + "-app", "entrypoint": ["/bin/false"],
                "environment": environment, "labels": labels, "volumes": ["appdata:/data"],
                "networks": ["isolated"], "restart": "no", "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]},
        "db": {"image": services["db"]["image"], "labels": labels,
               "environment": {key: restored[key] for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")},
               "volumes": ["pgdata:/var/lib/postgresql/data"], "networks": ["isolated"], "restart": "no",
               "healthcheck": {"test": ["CMD-SHELL", 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
                               "interval": "2s", "timeout": "5s", "retries": 30}}},
        "volumes": {key: {"labels": labels} for key in ("appdata", "pgdata")},
        "networks": {"isolated": {"internal": True, "labels": labels}}}
    return profile, restored


def _owned_resources(docker, receipt):
    project, token = receipt["project"], receipt["token"]
    container_data = docker.run(["ps", "-aq", "--no-trunc", "--filter", "label=com.docker.compose.project=" + project], compose=False)
    containers = container_data.decode("ascii").splitlines()
    volumes = docker.run(["volume", "ls", "--format", "{{.Name}}", "--filter", "label=com.docker.compose.project=" + project], compose=False).decode().splitlines()
    networks = docker.run(["network", "ls", "--no-trunc", "--format", "{{.ID}}", "--filter", "label=com.docker.compose.project=" + project], compose=False).decode("ascii").splitlines()
    for kind, values in (("container", containers), ("volume", volumes), ("network", networks)):
        for value in values:
            if kind != "volume" and not re.fullmatch(r"[a-f0-9]{64}", value):
                raise BackupError("Probe-Ressourcenidentität ist nicht prüfbar.")
            args = ["inspect", value] if kind == "container" else [kind, "inspect", value]
            info = json.loads(docker.run(args, compose=False))
            if not isinstance(info, list) or len(info) != 1:
                raise BackupError("Probe-Ressourcenidentität ist nicht prüfbar.")
            labels = info[0].get("Config", {}).get("Labels", {}) if kind == "container" else info[0].get("Labels", {})
            if labels.get(OWNER_LABEL) != token or labels.get("com.docker.compose.project") != project:
                raise BackupError("Fremde Probe-Ressource: Bereinigung verweigert.")
    return containers, volumes, networks


def cleanup(docker, receipt):
    """Inspect every resource before removing any exact owned daemon object."""
    containers, volumes, networks = _owned_resources(docker, receipt)
    image_name = receipt["project"] + "-app"
    images = docker.run(["image", "ls", "--no-trunc", "--format", "{{.ID}}", image_name], compose=False).decode().splitlines()
    if images:
        info = json.loads(docker.run(["image", "inspect", image_name], compose=False))
        if len(info) != 1 or info[0].get("Config", {}).get("Labels", {}).get(OWNER_LABEL) != receipt["token"]:
            raise BackupError("Fremdes Probeimage: Bereinigung verweigert.")
    for container in containers:
        docker.run(["rm", "-f", container], compose=False, stage="Eigene Probecontainer entfernen")
    for volume in volumes:
        docker.run(["volume", "rm", volume], compose=False, stage="Eigene Probevolumes entfernen")
    for network in networks:
        docker.run(["network", "rm", network], compose=False, stage="Eigenes Probenetz entfernen")
    if images:
        docker.run(["image", "rm", image_name], compose=False, stage="Eigenes Probeimage entfernen")


def cleanup_receipt(receipt, compose_file, limits=Limits()):
    if (not isinstance(receipt, dict) or not re.fullmatch(r"immo-probe-[a-f0-9]{32}", receipt.get("project", ""))
            or not re.fullmatch(r"[a-f0-9]{32}", receipt.get("token", ""))):
        raise BackupError("Probe-Eigentumsbeleg ist ungültig.")
    with private_workspace() as (workspace, _):
        with _new_file(workspace / "empty.env") as output:
            output.write(b"# raw daemon cleanup only\n")
        docker = Docker(compose_file, workspace / "empty.env", receipt["project"], workspace, limits, Deadline(min(120, limits.timeout_seconds)))
        cleanup(docker, receipt)


def probe_restore(*, source: Path, compose_file: Path, password: str, limits=Limits(), ownership=None, docker_factory=Docker):
    """No original listener, app entrypoint, connectors or host mount are started."""
    deadline = Deadline(limits.timeout_seconds)
    compose_file = _safe_path(compose_file)
    with private_workspace() as (workspace, _):
        manifest = verify_package(source, password, workspace, limits, deadline)
        if _compose_digest(compose_file, limits, deadline) != manifest["compose_sha256"]:
            raise BackupError("Compose-Profil stimmt nicht mit dem Sicherungsmanifest überein.")
        receipt = {"project": "immo-probe-" + uuid4().hex, "token": uuid4().hex}
        original = _parse_env(_read_file(workspace / "server.env", limits.small_bytes, deadline))
        source_workspace = workspace / "source-profile"
        source_workspace.mkdir(mode=0o700)
        source_docker = docker_factory(compose_file, workspace / "server.env", receipt["project"], source_workspace, limits, deadline)
        if getattr(source_docker, "compose_digest", None) != manifest["compose_sha256"]:
            raise BackupError("Compose-Profil wurde während des Lesens verändert.")
        source_docker.require_private_volumes()
        config = _json(source_docker.run(["config", "--format", "json"], stage="Originalprofil für Probe prüfen"))
        profile, _ = _profile(config, receipt["project"], receipt["token"], original)
        derived = workspace / "portless-profile.json"
        with _new_file(derived) as output:
            output.write(json.dumps(profile, separators=(",", ":")).encode())
        derived_workspace = workspace / "derived-profile"
        derived_workspace.mkdir(mode=0o700)
        docker = docker_factory(derived, workspace / "server.env", receipt["project"], derived_workspace, limits, deadline)
        # require_new_project also refuses any preexisting project-named resource.
        docker.require_new_project()
        docker.require_private_volumes()
        if ownership is not None:
            ownership(receipt)  # Durable before any resource is built/created.
        try:
            docker.run(["build", "app"], stage="Isoliertes Probeimage bauen")
            docker.require_new_project()
            guard = docker.run(["create", "--name", receipt["project"] + "-restore-guard", "--label",
                "com.docker.compose.project=" + receipt["project"], "--label", OWNER_LABEL + "=" + receipt["token"],
                "--entrypoint", "/bin/true", receipt["project"] + "-app"], compose=False, stage="Probeprojekt reservieren")
            if not re.fullmatch(rb"[a-f0-9]{64}\s*", guard):
                raise BackupError("Probe-Projektreservierung ist nicht prüfbar.")
            docker.run(["up", "-d", "--wait", "--wait-timeout", "120", "db"], stage="Isolierte Probedatenbank starten")
            docker.run(["exec", "-T", "db", "/bin/sh", "-c", PG_RESTORE], input_file=workspace / "database.dump", stage="Probedatenbank wiederherstellen")
            docker.run(["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "app", "-C", "/data", "-xzf", "-",
                        "--no-same-owner", "--no-same-permissions"], input_file=workspace / "appdata.tar.gz", stage="Probeappdaten wiederherstellen")
            with _new_file(workspace / "restore-keys.json") as output:
                output.write(json.dumps(original, separators=(",", ":")).encode())
            report = _json(docker.run(["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-m",
                "scripts.restore_session_security", "--configuration-stdin", "--timeout-seconds", str(deadline.remaining())],
                input_file=workspace / "restore-keys.json", stage="Probesitzungen widerrufen"))
            if (set(report) != {"revoked_session_count", "legacy_iban_present"}
                    or type(report["revoked_session_count"]) is not int or report["revoked_session_count"] < 0
                    or type(report["legacy_iban_present"]) is not bool):
                raise BackupError("Sicherheitsabschluss der Probe nicht bestätigt.")
            verification = _json(docker.run(["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-m",
                "scripts.verify_private_server_probe", "--archive-stdin", "--max-entries", str(limits.entries),
                "--max-bytes", str(limits.expanded_data_bytes), "--timeout-seconds", str(deadline.remaining())],
                input_file=workspace / "appdata.tar.gz", maximum=limits.metadata_bytes, stage="Wirkliche Probedaten prüfen"))
            if verification.get("verified") is not True or docker.running("app"):
                raise BackupError("Isolierte Probe wurde nicht bestätigt.")
            if "database" in manifest and verification.get("database") != manifest["database"]:
                raise BackupError("Probedatenbank stimmt nicht mit dem Quellinventar überein.")
            return {"kind": "private_server", "portless": True, "project": receipt["project"],
                    "sessions_revoked": report["revoked_session_count"], "signing_key_rotated": True,
                    "database_tables": len(verification["database"]["rows"]), "upload_files": verification["upload_files"],
                    "source_inventory_verified": "database" in manifest}
        finally:
            docker.deadline = Deadline(min(120, limits.timeout_seconds))
            # The receipt also survives build/guard failures and process death.
            # Refuse foreign resources; never down the original source project.
            cleanup(docker, receipt)
            if ownership is not None:
                ownership(None)
