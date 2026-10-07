"""Archived originals on a real PostgreSQL server: migration, triggers, row locks, account fence.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL pointing at a disposable loopback
PostgreSQL server with CREATE DATABASE permission. Each test owns a new
immoqa_archive_<uuid> database and drops only that database afterwards.
"""

import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from archive_helpers import lease_with_document, pdf_bytes
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

import backend.models  # noqa: F401 (register the UI contract columns)
from backend import auth
from backend.repositories import SQLAlchemyStore
from backend.services import document_versions as archive
from backend.services.document_version_validation import verify_document_versions

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"
ARCHIVE_PARENT = "d7a2f9c4e681"


@pytest.fixture
def postgres(monkeypatch):
    admin_url = os.getenv("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for real PostgreSQL archive tests")
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL archive tests require an explicitly configured loopback server")
    name = f"immoqa_archive_{uuid4().hex}"
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    test_url = url.set(database=name)
    engine = sa.create_engine(test_url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    monkeypatch.setenv("DATABASE_URL", test_url.render_as_string(hide_password=False))
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        command.upgrade(config, "head")
        # accounts in this database, as in production: the fence locks their rows
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(engine)))
        yield engine, config
    finally:
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _archive(target, lease, actor_id, content, version_id="v1"):
    document = lease["document"]
    with archive.work(target, actor_id, write_areas=("/documents",)) as unit:
        _, binding = archive.bind_document(unit, document.id, lock=True)
        return archive.publish_generated_original(unit, document, binding, content, "a" * 64,
                                                  version_id=version_id)


def test_originals_on_postgres_are_immutable_and_survive_a_downgrade_attempt(postgres):
    engine, config = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    target = _store(engine)
    lease = lease_with_document(target)
    content = pdf_bytes(150_000)
    _archive(target, lease, owner.id, content)

    with archive.work(target, owner.id) as unit:
        row = archive.head(unit, lease["document"].id)
        assert row is not None and archive.original_bytes(unit, row) == content
    for statement in ("UPDATE document_versions SET comment = 'x'", "DELETE FROM document_version_chunks"):
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.exec_driver_sql(statement)
    with engine.connect() as connection:
        assert verify_document_versions(connection) == 1
    with pytest.raises(RuntimeError, match="Document originals exist"):
        command.downgrade(config, ARCHIVE_PARENT)
    target.db.close()


def test_two_publications_of_the_same_document_serialize_on_postgres(postgres):
    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    lease = lease_with_document(_store(engine))
    outcomes: list = []

    def publish(version_id):
        try:
            _archive(_store(engine), lease, owner.id, pdf_bytes(70_000), version_id=version_id)
            outcomes.append("ok")
        except HTTPException as error:
            outcomes.append(error.status_code)

    workers = [threading.Thread(target=publish, args=(f"v{index}",)) for index in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)

    assert sorted(outcomes, key=str) == [409, 409, 409, "ok"]
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM document_versions").scalar() == 1


def test_a_role_change_waits_for_the_running_publication_on_postgres(postgres):
    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    target = _store(engine)
    lease = lease_with_document(target)
    changed = threading.Event()

    def take_role_away():
        auth.update_user(owner.id, {"role": "readonly"})
        changed.set()

    document = lease["document"]
    with archive.work(target, owner.id, write_areas=("/documents",)) as unit:
        worker = threading.Thread(target=take_role_away)
        worker.start()
        time.sleep(0.5)
        assert not changed.is_set()            # the share lock on the account row holds it back
        _, binding = archive.bind_document(unit, document.id, lock=True)
        archive.publish_generated_original(unit, document, binding, pdf_bytes(500), "b" * 64, version_id="v1")
    worker.join(10)

    assert changed.is_set()
    with pytest.raises(HTTPException) as error:
        _archive(target, lease, owner.id, pdf_bytes(10), version_id="v2")
    assert error.value.status_code == 403
    target.db.close()


def test_parallel_publications_of_one_confirmation_store_one_original(postgres):
    """Same command key from several requests at once: one original, every answer names it."""
    from backend.services import housing_confirmation as housing
    from backend.services.housing_confirmation_types import PreviewRequest, SaveRequest

    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    lease = lease_with_document(_store(engine))
    contract_id = lease["contract"].id
    etags = housing.source(_store(engine), contract_id, owner.id)["source_etags"]
    data = {"housing_provider_name": "Linda Reiser", "housing_provider_address": "Prießnitzstraße 4\n01099 Dresden",
            "owner_same_as_provider": True, "owner_name": None, "move_in_date": "2026-02-03",
            "issue_date": "2026-10-07", "apartment_address": "Bautzner Straße 61\n01099 Dresden",
            "apartment_label": "WE 3", "issuer_name": "Linda Reiser", "issuer_role": "housing_provider",
            "residents": ["Mia Muster", "Zoë Beispiel"]}
    preview = PreviewRequest.model_validate({"data": data, "source_etags": etags})
    review = housing.preview(_store(engine), contract_id, preview, owner.id)
    command = SaveRequest.model_validate({**preview.model_dump(mode="json"), "idempotency_key": "parallel",
                                          "review_hash": review["review_hash"], "confirmed_actual_move_in": True,
                                          "confirmed_authority": True, "confirmed_residents": True})
    answers: list = []

    def publish():
        target = _store(engine)
        try:
            answers.append(housing.publish(target, contract_id, command, owner.id)["version_id"])
        finally:
            target.db.close()

    workers = [threading.Thread(target=publish) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)

    assert len(answers) == 4 and len(set(answers)) == 1
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM document_versions").scalar() == 1
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM documents WHERE document_type = 'housing_confirmation'").scalar() == 1
        assert verify_document_versions(connection) == 1


def _housing_command(engine, owner, contract_id, key, **changes):
    from backend.services import housing_confirmation as housing
    from backend.services.housing_confirmation_types import PreviewRequest, SaveRequest

    etags = housing.source(_store(engine), contract_id, owner.id)["source_etags"]
    data = {"housing_provider_name": "Linda Reiser", "housing_provider_address": "Prießnitzstraße 4\n01099 Dresden",
            "owner_same_as_provider": True, "owner_name": None, "move_in_date": "2026-02-03",
            "issue_date": "2026-10-07", "apartment_address": "Bautzner Straße 61\n01099 Dresden",
            "apartment_label": "WE 3", "issuer_name": "Linda Reiser", "issuer_role": "housing_provider",
            "residents": ["Mia Muster"], **changes.pop("data", {})}
    preview = PreviewRequest.model_validate({"data": data, "source_etags": etags, **changes})
    review = housing.preview(_store(engine), contract_id, preview, owner.id)
    return SaveRequest.model_validate({**preview.model_dump(mode="json"), "idempotency_key": key,
                                       "review_hash": review["review_hash"], "confirmed_actual_move_in": True,
                                       "confirmed_authority": True, "confirmed_residents": True})


def _publish_housing(engine, contract_id, command, actor_id):
    from backend.services import housing_confirmation as housing

    target = _store(engine)
    try:
        return housing.publish(target, contract_id, command, actor_id)
    finally:
        target.db.close()


def test_confirmation_replay_conflict_stale_source_and_correction_on_postgres(postgres):
    """The single-request rules of the confirmation, on PostgreSQL row locks and triggers."""
    from backend.services import housing_confirmation as housing

    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    lease = lease_with_document(_store(engine))
    contract_id = lease["contract"].id

    first_command = _housing_command(engine, owner, contract_id, "first")
    first = _publish_housing(engine, contract_id, first_command, owner.id)
    # the answer was lost: the same command again names the same original
    assert _publish_housing(engine, contract_id, first_command, owner.id)["version_id"] == first["version_id"]
    # another command under the same key is refused, not stored
    other = _housing_command(engine, owner, contract_id, "first", data={"residents": ["Jemand Anderes"]})
    with pytest.raises(HTTPException) as conflict:
        _publish_housing(engine, contract_id, other, owner.id)
    assert conflict.value.status_code == 409

    # the contract changes after the review: nothing is written
    stale = _housing_command(engine, owner, contract_id, "stale")
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE contracts SET updated_at = now() + interval '1 second' WHERE id = %s",
                                   (contract_id,))
    with pytest.raises(HTTPException) as gone:
        _publish_housing(engine, contract_id, stale, owner.id)
    assert gone.value.status_code == 412

    first_bytes = housing.read_original(_store(engine), contract_id, first["document_id"], owner.id)[0]
    correction = _housing_command(engine, owner, contract_id, "correction",
                                  data={"residents": ["Mia Muster", "Nachgetragene Person"]},
                                  correction_of={"document_id": first["document_id"],
                                                 "version_id": first["version_id"]})
    second = _publish_housing(engine, contract_id, correction, owner.id)

    assert second["document_id"] != first["document_id"]
    assert housing.read_original(_store(engine), contract_id, first["document_id"], owner.id)[0] == first_bytes
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM document_versions").scalar() == 2
        assert verify_document_versions(connection) == 2
