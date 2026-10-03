"""Real SQL-session concurrency gates for the tenancy workflow core.

SQLite uses independent connections against one WAL database. PostgreSQL uses a
fresh random schema per test. Tests coordinate at the writer boundary with
threading.Barrier; no sleeps are used as concurrency evidence.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from threading import Barrier, Lock, local
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend import auth
from backend.db.document_version_models import (
    DocumentVersionChunkORM,
    DocumentVersionORM,
)
from backend.db.orm_models import Base
from backend.db.tenancy_workflow_models import (
    TenancyChangeORM,
    WorkflowCommandORM,
    WorkflowEvidenceLinkORM,
    WorkflowStepInstanceORM,
)
from backend.models import (
    ContractCreate,
    DocumentCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_versions
from backend.services import tenancy_workflow as workflow
from backend.services.tenancy_workflow_types import (
    AddEvidence,
    CreateTemplate,
    EvidenceInput,
    PublishTemplateVersion,
    StartTenancyChange,
    TemplateStepInput,
    UpdateStep,
)


@dataclass
class Scenario:
    engine: Engine
    portfolio_id: str
    property_id: str
    unit_id: str
    contract_id: str
    template_version_id: str


@pytest.fixture(params=["sqlite", "postgres"])
def scenario(request, tmp_path, monkeypatch):
    engine = admin = None
    schema = None
    if request.param == "sqlite":
        engine = create_engine(
            "sqlite:///" + (tmp_path / "workflow-concurrency.db").as_posix(),
            connect_args={"check_same_thread": False, "timeout": 20},
            pool_size=8,
        )

        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=20000")

    else:
        source = os.getenv("TEST_SERVER_DATABASE_URL")
        if not source:
            pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL is not configured")
        url = make_url(source)
        if url.get_backend_name() != "postgresql":
            pytest.fail("TEST_SERVER_DATABASE_URL must reference PostgreSQL")
        schema = "tenancy_concurrency_" + uuid4().hex
        admin = create_engine(url, hide_parameters=True, pool_pre_ping=True)
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped = url.update_query_dict({"options": "-csearch_path=" + schema})
        engine = create_engine(
            scoped,
            hide_parameters=True,
            pool_pre_ping=True,
            pool_size=8,
            max_overflow=4,
        )

    Base.metadata.create_all(engine)
    migration = __import__(
        "backend.db.migrations.versions.b2a2b3c4d5e6_tenancy_workflows",
        fromlist=["install_guards"],
    )
    with engine.begin() as connection:
        migration.install_guards(connection)

    user = {
        "id": "manager",
        "full_name": "Synthetic Manager",
        "role": "verwalter",
        "is_active": True,
        "portfolio_access": "selected",
        "portfolio_ids": [],
    }
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: user if identifier == "manager" else None)

    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        portfolio = store.create_portfolio(PortfolioCreate(name="Concurrency portfolio"))
        user["portfolio_ids"] = [portfolio.id]
        prop = store.create_property(
            PropertyCreate(
                portfolio_id=portfolio.id,
                name="Concurrency property",
                property_type="residential",
            )
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="C-1", unit_type="apartment")
        )
        tenant = store.create_tenant(TenantCreate(full_name="Synthetic Tenant"))
        contract = store.create_contract(
            ContractCreate(
                contract_number="CONCURRENT-OLD",
                property_id=prop.id,
                unit_id=unit.id,
                tenant_id=tenant.id,
                start_date=date(2020, 1, 1),
                end_date=date(2026, 12, 31),
                status="terminated",
            )
        )
        draft = workflow.create_template(
            store,
            CreateTemplate(
                idempotency_key="seed-template",
                expected_revision="new",
                property_id=prop.id,
                direction="move_out",
                steps=[
                    TemplateStepInput(
                        stable_key="handover",
                        position=0,
                        title="Synthetic handover",
                        description="Concurrency gate",
                        default_requirement="required",
                        anchor="move_out_handover",
                        offset_days=0,
                        assignee_role="techniker",
                        evidence_requirement="none",
                    )
                ],
            ),
            "manager",
        )
        published = workflow.publish_template_version(
            store,
            draft["id"],
            PublishTemplateVersion(
                idempotency_key="seed-template-publish",
                expected_revision=draft["revision"],
            ),
            "manager",
        )
        result = Scenario(
            engine=engine,
            portfolio_id=portfolio.id,
            property_id=prop.id,
            unit_id=unit.id,
            contract_id=contract.id,
            template_version_id=published["id"],
        )

    try:
        yield result
    finally:
        engine.dispose()
        if admin is not None and schema is not None:
            try:
                with admin.begin() as connection:
                    connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            finally:
                admin.dispose()


def _preview(scenario: Scenario):
    with Session(scenario.engine) as db:
        return workflow.preview_change(
            SQLAlchemyStore(db),
            workflow.PreviewTenancyChange(
                property_id=scenario.property_id,
                unit_id=scenario.unit_id,
                previous_contract_id=scenario.contract_id,
                mode="move_out",
                move_out_handover_date=date(2026, 12, 30),
                move_out_template_version_id=scenario.template_version_id,
            ),
            "manager",
        )


def _start_payload(scenario: Scenario, key: str) -> StartTenancyChange:
    preview = _preview(scenario)
    return StartTenancyChange(
        property_id=scenario.property_id,
        unit_id=scenario.unit_id,
        previous_contract_id=scenario.contract_id,
        mode="move_out",
        move_out_handover_date=date(2026, 12, 30),
        move_out_template_version_id=scenario.template_version_id,
        idempotency_key=key,
        expected_revision="new",
        preview_hash=preview["preview_hash"],
        source_etags=preview["source_etags"],
    )


def _worker(engine: Engine, operation):
    with Session(engine) as db:
        try:
            return "ok", operation(SQLAlchemyStore(db))
        except BaseException as exc:  # captured for exact post-join assertions
            return "error", exc


def _parallel_at_writer(monkeypatch, engine: Engine, operations):
    """Release two independent service sessions at their first writer boundary."""
    original = workflow.begin_writer
    barrier = Barrier(2, timeout=20)
    local_state = local()
    identities: set[object] = set()
    identity_lock = Lock()

    def gated(db):
        if not getattr(local_state, "released", False):
            connection = db.connection()
            raw = connection.connection.driver_connection
            identity = raw.get_backend_pid() if hasattr(raw, "get_backend_pid") else id(raw)
            with identity_lock:
                identities.add(identity)
            local_state.released = True
            barrier.wait()
        return original(db)

    monkeypatch.setattr(workflow, "begin_writer", gated)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(_worker, engine, operation)
                for operation in operations
            ]
            results = [future.result(timeout=30) for future in futures]
    finally:
        monkeypatch.setattr(workflow, "begin_writer", original)
    assert len(identities) == 2, "the race must use two independent DB connections/workers"
    return results


def _counts(engine: Engine, *, start_key: str | None = None):
    with Session(engine) as db:
        changes = db.scalar(select(func.count()).select_from(TenancyChangeORM))
        query = select(func.count()).select_from(WorkflowCommandORM).where(
            WorkflowCommandORM.operation == "start_tenancy_change"
        )
        if start_key is not None:
            query = query.where(WorkflowCommandORM.idempotency_key == start_key)
        starts = db.scalar(query)
        return int(changes or 0), int(starts or 0)


def test_same_start_key_creates_one_change_and_replays(scenario, monkeypatch):
    payload = _start_payload(scenario, "same-start-key")
    results = _parallel_at_writer(
        monkeypatch,
        scenario.engine,
        [
            lambda store: workflow.start_change(store, payload, "manager"),
            lambda store: workflow.start_change(store, payload, "manager"),
        ],
    )

    assert [status for status, _ in results] == ["ok", "ok"]
    first, second = results[0][1], results[1][1]
    assert first == second
    assert first["id"] == second["id"]
    assert _counts(scenario.engine, start_key="same-start-key") == (1, 1)

    with Session(scenario.engine) as db:
        replay = workflow.start_change(SQLAlchemyStore(db), payload, "manager")
    assert replay == first
    assert _counts(scenario.engine, start_key="same-start-key") == (1, 1)


def test_different_start_keys_same_contract_role_have_exactly_one_winner(scenario, monkeypatch):
    first = _start_payload(scenario, "competing-start-a")
    second = first.model_copy(update={"idempotency_key": "competing-start-b"})
    results = _parallel_at_writer(
        monkeypatch,
        scenario.engine,
        [
            lambda store: workflow.start_change(store, first, "manager"),
            lambda store: workflow.start_change(store, second, "manager"),
        ],
    )

    winners = [value for status, value in results if status == "ok"]
    losers = [value for status, value in results if status == "error"]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], HTTPException)
    assert losers[0].status_code == 409

    with Session(scenario.engine) as db:
        assert db.scalar(
            select(func.count()).select_from(TenancyChangeORM).where(
                TenancyChangeORM.state == "active",
                TenancyChangeORM.previous_contract_id == scenario.contract_id,
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(WorkflowCommandORM).where(
                WorkflowCommandORM.operation == "start_tenancy_change",
                WorkflowCommandORM.idempotency_key.in_(
                    ("competing-start-a", "competing-start-b")
                ),
            )
        ) == 1


def _document_evidence_change(scenario: Scenario):
    payload = _start_payload(scenario, "step-race-start")
    with Session(scenario.engine) as db:
        store = SQLAlchemyStore(db)
        change = workflow.start_change(store, payload, "manager")
        step = change["steps"][0]
        document = store.create_document(
            DocumentCreate(
                property_id=scenario.property_id,
                unit_id=scenario.unit_id,
                contract_id=scenario.contract_id,
                title="Synthetic immutable original",
                document_type="handover_attachment",
                document_date=date(2026, 12, 30),
                file_url="/uploads/concurrency-original.pdf",
            )
        )
    content = b"%PDF-1.4\nsynthetic concurrency original\n%%EOF\n"
    with Session(scenario.engine) as db:
        store = SQLAlchemyStore(db)
        with document_versions.work(store, "manager", write=True) as (active, owned, _):
            actual, binding = document_versions._document(active, owned, document.id, lock=True)
            version = document_versions.publish_generated_original(
                active,
                owned,
                actual,
                binding,
                "manager",
                content,
                "c" * 64,
            )
    with Session(scenario.engine) as db:
        linked = workflow.add_evidence(
            SQLAlchemyStore(db),
            change["id"],
            step["id"],
            AddEvidence(
                idempotency_key="step-race-evidence",
                expected_revision=step["revision"],
                expected_change_revision=change["revision"],
                evidence=EvidenceInput(
                    kind="document_version",
                    document_id=document.id,
                    document_version_id=version.id,
                ),
            ),
            "manager",
        )
        current = workflow.get_change(SQLAlchemyStore(db), change["id"], "manager")
    step = next(item for item in current["steps"] if item["id"] == linked["id"])
    return current, step, version.id, linked["evidence_links"][0]["id"]


def _original_snapshot(engine: Engine, version_id: str, link_id: str):
    with Session(engine) as db:
        version = db.get(DocumentVersionORM, version_id)
        link = db.get(WorkflowEvidenceLinkORM, link_id)
        assert version is not None and link is not None
        chunks = list(
            db.execute(
                select(
                    DocumentVersionChunkORM.position,
                    DocumentVersionChunkORM.portfolio_id,
                    DocumentVersionChunkORM.data,
                )
                .where(DocumentVersionChunkORM.version_id == version_id)
                .order_by(DocumentVersionChunkORM.position)
            )
        )
        return {
            "version": (
                version.id,
                version.document_id,
                version.portfolio_id,
                version.property_id,
                version.unit_id,
                version.contract_id,
                version.tenant_id,
                version.number,
                version.sha256,
                version.size_bytes,
                deepcopy(version.metadata_snapshot),
            ),
            "chunks": [(position, portfolio_id, bytes(data)) for position, portfolio_id, data in chunks],
            "link": (
                link.id,
                link.tenancy_change_id,
                link.step_id,
                link.portfolio_id,
                link.kind,
                link.document_id,
                link.document_version_id,
                link.snapshot_sha256,
                link.created_by,
                link.created_at,
            ),
        }


def test_parallel_step_cas_has_one_winner_and_preserves_original_evidence(scenario, monkeypatch):
    change, step, version_id, link_id = _document_evidence_change(scenario)
    before = _original_snapshot(scenario.engine, version_id, link_id)

    common = {
        "expected_revision": step["revision"],
        "expected_change_revision": change["revision"],
        "state": "completed",
    }
    left = UpdateStep(idempotency_key="step-race-left", **common)
    right = UpdateStep(idempotency_key="step-race-right", **common)
    results = _parallel_at_writer(
        monkeypatch,
        scenario.engine,
        [
            lambda store: workflow.update_step(
                store, change["id"], step["id"], left, "manager"
            ),
            lambda store: workflow.update_step(
                store, change["id"], step["id"], right, "manager"
            ),
        ],
    )

    winners = [value for status, value in results if status == "ok"]
    losers = [value for status, value in results if status == "error"]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], HTTPException)
    assert losers[0].status_code == 409
    assert winners[0]["state"] == "completed"

    after = _original_snapshot(scenario.engine, version_id, link_id)
    assert after == before

    with Session(scenario.engine) as db:
        stored_step = db.get(WorkflowStepInstanceORM, step["id"])
        assert stored_step is not None
        assert stored_step.state == "completed"
        assert db.scalar(
            select(func.count()).select_from(WorkflowCommandORM).where(
                WorkflowCommandORM.operation == "update_workflow_step",
                WorkflowCommandORM.idempotency_key.in_(
                    ("step-race-left", "step-race-right")
                ),
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(WorkflowEvidenceLinkORM).where(
                WorkflowEvidenceLinkORM.id == link_id
            )
        ) == 1
