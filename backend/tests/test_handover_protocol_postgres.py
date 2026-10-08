"""Handover protocols on a real PostgreSQL server: migration, finalization, triggers, readings, downgrade.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL pointing at a disposable loopback PostgreSQL
server with CREATE DATABASE permission. Each test owns a new immoqa_handover_<uuid>
database and drops only that database afterwards.
"""

import os
import threading
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

import backend.models  # noqa: F401 (register the UI contract columns)
from backend import auth
from backend.models import ContractCreate, MeterCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories import SQLAlchemyStore
from backend.services import handover_protocol as service
from backend.services.document_version_validation import verify_document_versions
from backend.services.handover_protocol_types import ContentRequest, CreateRequest, FinalizeRequest, FollowUpRequest

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"
HANDOVER_PARENT = "f3b9c1d7e2a5"


@pytest.fixture
def postgres(monkeypatch):
    admin_url = os.getenv("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for real PostgreSQL handover tests")
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL handover tests require an explicitly configured loopback server")
    name = f"immoqa_handover_{uuid.uuid4().hex}"
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


def _estate(target):
    portfolio = target.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                 property_type="residential"))
    unit = target.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential", rooms=1))
    tenant = target.create_tenant(TenantCreate(full_name="Mia Muster"))
    contract = target.create_contract(ContractCreate(contract_number="V-1", property_id=prop.id, unit_id=unit.id,
                                                     tenant_id=tenant.id, start_date=date(2024, 1, 1),
                                                     end_date=date(2026, 6, 30), status="terminated"))
    meter = target.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water", serial_number="KW-1"))
    return contract, meter


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _finalized(engine, owner):
    contract, meter = _estate(_store(engine))
    detail = service.create_from_contract(_store(engine), CreateRequest(contract_id=contract.id,
                                                                        protocol_type="move_out"), owner.id)
    protocol_id = detail["protocol"]["id"]
    rooms = [{"id": r["id"], "name": r["name"], "condition": "good"} for r in detail["rooms"]]
    detail = service.save_content(_store(engine), protocol_id, ContentRequest(
        base_revision=detail["protocol"]["revision"], protocol_date=date(2026, 6, 30),
        tenant_signature="Mia Muster", landlord_signature="Linda Reiser", rooms=rooms,
        defects=[{"id": str(uuid.uuid4()), "room_id": rooms[0]["id"], "description": "Kratzer im Parkett",
                  "responsible": "tenant"}],
        keys=[{"id": str(uuid.uuid4()), "key_type": "apartment_door", "handed_over": 2, "returned": 2}],
        meter_readings=[{"id": str(uuid.uuid4()), "meter_id": meter.id, "reading_value": 130.25}]), owner.id)
    service.add_photo(_store(engine), protocol_id, _png(), "parkett.png", "image/png",
                      {"room_id": None, "defect_id": detail["defects"][0]["id"], "meter_reading_id": None},
                      "Kratzer", owner.id)
    preview = service.preview(_store(engine), protocol_id, owner.id)
    assert preview["ready"], preview["problems"]
    return protocol_id, meter, preview


def test_finalized_protocols_on_postgres_are_immutable_and_feed_the_meter(postgres):
    engine, config = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    protocol_id, meter, preview = _finalized(engine, owner)
    final = service.finalize(_store(engine), protocol_id, FinalizeRequest(
        idempotency_key="pg-1", review_hash=preview["review_hash"], confirmed_content=True,
        confirmed_signatures=True), owner.id)
    assert final["state"]["finalized"] and final["original"]["content_matches"]
    content, row = service.read_original(_store(engine), protocol_id, owner.id)
    assert row.sha256 == preview["pdf_sha256"] and content.startswith(b"%PDF-")

    with engine.connect() as connection:
        readings = connection.execute(sa.text("SELECT reading_date, value FROM standalone_meter_readings "
                                              "WHERE meter_id = :m"), {"m": meter.id}).all()
        assert [(day, float(value)) for day, value in readings] == [(date(2026, 6, 30), 130.25)]
        assert verify_document_versions(connection) == 1
    for statement in ("UPDATE handover_protocols SET notes = 'x' WHERE id = :id",
                      "DELETE FROM handover_protocols WHERE id = :id",
                      "UPDATE handover_rooms SET name = 'x' WHERE protocol_id = :id",
                      "DELETE FROM handover_photos WHERE protocol_id = :id",
                      "UPDATE meter_readings SET reading_value = 1 WHERE handover_id = :id",
                      "UPDATE handover_defects SET responsible = 'landlord' WHERE protocol_id = :id",
                      "DELETE FROM handover_defects WHERE protocol_id = :id"):
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.execute(sa.text(statement), {"id": protocol_id})
    followed = service.follow_up(_store(engine), protocol_id, final["defects"][0]["id"],
                                 FollowUpRequest(resolved_at=date(2026, 7, 20), resolution_note="geschliffen"),
                                 owner.id)
    assert followed["defects"][0]["resolved_at"] == "2026-07-20"

    with pytest.raises(RuntimeError, match="Handover protocol data exists"):
        command.downgrade(config, HANDOVER_PARENT)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "a4d8e2f6c1b9"


def test_two_finalizations_of_one_protocol_serialize_on_postgres(postgres):
    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    protocol_id, meter, preview = _finalized(engine, owner)
    outcomes: list = []

    def finalize(key):
        try:
            service.finalize(_store(engine), protocol_id, FinalizeRequest(
                idempotency_key=key, review_hash=preview["review_hash"], confirmed_content=True,
                confirmed_signatures=True), owner.id)
            outcomes.append("ok")
        except HTTPException as error:
            outcomes.append(error.status_code)

    workers = [threading.Thread(target=finalize, args=(f"key-{index}",)) for index in range(3)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert sorted(outcomes, key=str) == [409, 409, "ok"]
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM document_versions").scalar() == 1
        assert connection.execute(sa.text("SELECT count(*) FROM standalone_meter_readings WHERE meter_id = :m"),
                                  {"m": meter.id}).scalar() == 1


def test_the_handover_migration_goes_down_and_up_without_data_on_postgres(postgres):
    engine, config = postgres
    command.downgrade(config, HANDOVER_PARENT)
    inspector = sa.inspect(engine)
    assert "handover_rooms" not in inspector.get_table_names()
    assert "finalized_at" not in {c["name"] for c in inspector.get_columns("handover_protocols")}
    assert "meter_id" not in {c["name"] for c in inspector.get_columns("meter_readings")}
    command.upgrade(config, "head")
    inspector = sa.inspect(engine)
    assert {"handover_rooms", "handover_defects", "handover_keys", "handover_photos"} <= set(
        inspector.get_table_names())
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(sa.text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE :name"), {"name": "immo_%final"})}
    assert {"immo_handover_protocols_final", "immo_handover_rooms_final", "immo_handover_defects_final",
            "immo_handover_keys_final", "immo_handover_photos_final", "immo_meter_readings_final"} <= triggers
