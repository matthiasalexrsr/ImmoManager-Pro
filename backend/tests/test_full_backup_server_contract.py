"""Host lifecycle/profile contracts; these do not claim a real Docker deployment."""

import json

import pytest

from backend.tests import test_private_server_backup as private_fixtures
from backend.tests.test_private_server_backup import ENV, PASSWORD, DockerFixture, FakeDocker
from scripts import private_server_backup as tool
from scripts.private_server_probe import OWNER_LABEL, _profile

installation = private_fixtures.installation


class LifecycleDocker(FakeDocker):
    def app_identity(self):
        return [{"id": "a" * 64, "created": "2026-10-03T00:00:00Z"}]

    def run(self, args, **kwargs):
        if kwargs.get("stage") == "Quelltabelleninventar prüfen":
            self.fixture.events.append((self.project, kwargs["stage"], args))
            return json.dumps({"verified": True, "database": {"schema_sha256": "b" * 64, "rows": {"users": 3}}}).encode()
        return super().run(args, **kwargs)


class LifecycleFactory(DockerFixture):
    def __call__(self, *args):
        return LifecycleDocker(self, *args)


def test_lifecycle_receipt_precedes_stop_and_remains_until_verified_resume(installation):
    directory, env, compose = installation
    factory = LifecycleFactory()
    receipt = {}
    stages = []
    def lifecycle(stage, values):
        stages.append(stage)
        if stage == "prepared":
            assert factory.app_running["original"]  # Receipt precedes real stop command.
            receipt.update(values)
        elif stage == "resumed":
            assert factory.app_running["original"]
    archive = directory / "lifecycle.immobak"
    tool.backup(project="original", destination=archive, compose_file=compose, env_file=env, password=PASSWORD,
                docker_factory=factory, lifecycle=lifecycle)
    assert stages == ["prepared", "offline", "published", "resumed"]
    assert receipt["was_running"] and receipt["app_containers"]
    with tool.private_workspace() as (workspace, _):
        manifest = tool.verify_package(archive, PASSWORD, workspace, tool.Limits(), tool.Deadline(30))
        assert manifest["database"]["rows"] == {"users": 3}
    assert b"POSTGRES_PASSWORD" not in json.dumps(receipt).encode()


def test_failed_durable_prepare_does_not_stop_or_resume_original(installation):
    directory, env, compose = installation
    factory = LifecycleFactory()
    def fail_prepare(stage, _):
        assert stage == "prepared"
        raise OSError("journal storage unavailable")
    with pytest.raises(OSError):
        tool.backup(project="original", destination=directory / "failed.immobak", compose_file=compose,
                    env_file=env, password=PASSWORD, docker_factory=factory, lifecycle=fail_prepare)
    assert factory.app_running["original"]
    assert "App anhalten" not in factory.stages() and "App wieder starten" not in factory.stages()


def test_probe_profile_has_only_private_volumes_internal_network_and_fresh_credentials():
    original = tool._parse_env(ENV)
    config = {"services": {"app": {"build": {"context": "/synthetic/repo", "dockerfile": "Dockerfile.server"},
        "ports": [{"published": "8080", "target": 8000}], "environment": {"SMTP_PASSWORD": "synthetic-live-secret"}},
        "db": {"image": "postgres:16-alpine", "ports": [{"published": "5432"}]}}}
    profile, values = _profile(config, "immo-probe-" + "a" * 32, "b" * 32, original)
    assert values["POSTGRES_PASSWORD"] != original["POSTGRES_PASSWORD"]
    assert values["JWT_SECRET_KEY"] != original["JWT_SECRET_KEY"]
    assert profile["networks"]["isolated"]["internal"] is True
    assert profile["services"]["app"]["entrypoint"] == ["/bin/false"]
    assert profile["services"]["app"]["environment"]["OPERATIONAL_SCHEDULER_ENABLED"] == "false"
    for service in profile["services"].values():
        assert "ports" not in service and "network_mode" not in service
        assert service["labels"][OWNER_LABEL] == "b" * 32
    serialized = json.dumps(profile)
    assert "synthetic-live-secret" not in serialized and "https://example.test" not in serialized
    assert original["POSTGRES_PASSWORD"] not in serialized and original["JWT_SECRET_KEY"] not in serialized
