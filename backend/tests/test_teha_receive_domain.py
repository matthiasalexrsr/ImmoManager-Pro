"""DDL-free TEHA receive-domain gates with only synthetic provider data."""

from __future__ import annotations

import hashlib

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.auth import create_access_token
from backend.routers import teha as teha_router
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.integrations.history_store import SQLIntegrationHistoryStore
from backend.services.integrations.history_types import (
    HistoryActor,
    HistoryError,
    HistoryLimits,
)
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.providers.teha_field_manifest import classify_fields, manifest
from backend.services.providers.teha_import_projection import (
    document_projection,
    task_projection,
)
from backend.services.providers.teha_journal_reader import (
    JournaledTehaReader,
    history_exchange,
)
from backend.services.providers.teha_receive_contract import (
    ExplicitMapping,
    MappingIndex,
    PriorReceipt,
    ResumeCursor,
    classify_preview,
    document_evidence,
    mapping_digest,
    order_user_evidence,
    period_identity,
    property_identity,
    property_period_evidence,
    receive_batch,
    technical_order_evidence,
    unit_identity,
    user_identity,
)
from backend.services.providers.teha_transport import TehaTransport
from backend.services.providers.teha_types import (
    TehaDocument,
    TehaDocumentContent,
    TehaError,
    TehaOrderUser,
    TehaPropertyPeriod,
    TehaTechnicalOrder,
)
from backend.tests.test_integration_history_core import journal_engine

ACTOR = HistoryActor.internal("synthetic:teha-receive")
ACCESS = "synthetic-access-token"
REFRESH = "synthetic-refresh-token"
PASSWORD = "synthetic-password-never-persist"


def period_source(*, late=None):
    value = {
        "liegId": {"id": 41, "abrechnungLaufendeNr": 7},
        "liegenschaftenNummer": "SYNTHETIC-LIEG-41",
        "abrechnungVon": "2025-01-01T00:00:00",
        "abrechnungBis": "2025-12-31T00:00:00",
        "bezeichnung": "synthetic-display-only",
    }
    if late is not None:
        value["late_provider_extension"] = late
    return value


def period_dto(*, late=None):
    return TehaPropertyPeriod(
        object_id=41,
        period_number=7,
        lieg_nr="SYNTHETIC-LIEG-41",
        period_from_raw="2025-01-01T00:00:00",
        period_to_raw="2025-12-31T00:00:00",
        _source=period_source(late=late),
    )


def document_dto(*, late=None):
    source = {
        "reference": "opaque-ref-1",
        "fileName": "display-name.pdf",
        "properties": {
            "Liegenschafts_Nummer": "SYNTHETIC-LIEG-41",
            "Abrechnung_laufende_Nummer": 7,
        },
        "attachments": [],
    }
    if late is not None:
        source["late_document_extension"] = late
    return TehaDocument(
        reference="opaque-ref-1",
        filename="display-name.pdf",
        lieg_nr="SYNTHETIC-LIEG-41",
        _source=source,
    )


def content_dto():
    content = b"%PDF-1.4\nsynthetic TEHA original\n%%EOF\n"
    return TehaDocumentContent(
        reference="opaque-ref-1",
        lieg_nr="SYNTHETIC-LIEG-41",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def order_dto(*, late=None):
    source = {
        "terminId": 9001,
        "auftragNummer": 77,
        "abrLfdNr": 7,
        "liegenschaftsnummer": "SYNTHETIC-LIEG-41",
        "terminVon": "2026-01-10T08:00:00",
        "terminBis": "2026-01-10T12:00:00",
        "abrechnungBis": "2025-12-31T00:00:00",
        "statusText": "synthetic-provider-status",
    }
    if late is not None:
        source["late_order_extension"] = late
    return TehaTechnicalOrder(
        termin_id=9001,
        order_number=77,
        period_number=7,
        lieg_nr="SYNTHETIC-LIEG-41",
        termin_from_raw="2026-01-10T08:00:00",
        termin_to_raw="2026-01-10T12:00:00",
        period_to_raw="2025-12-31T00:00:00",
        _source=source,
    )


def mappings(*, generation=1, include_user=True):
    values = [
        ExplicitMapping(property_identity(41), "property", "property-local", generation),
        ExplicitMapping(period_identity(41, 7), "billing_period", "period-local", generation),
        ExplicitMapping(unit_identity("SYNTHETIC-LIEG-41", 501), "unit", "unit-local", generation),
    ]
    if include_user:
        values.append(
            ExplicitMapping(user_identity(9001, 601), "tenant", "tenant-local", generation)
        )
    return MappingIndex(values)


def test_value_free_manifest_never_drops_unknown_source_fields():
    report = manifest()
    assert report["policy"]["unknown_fields_are_preserved"] is True
    assert report["policy"]["manifest_is_not_an_allowlist"] is True
    assert "bezeichnung" in report["groups"]["property_period"]
    classified = classify_fields(
        "property_period",
        {"bezeichnung": "display", "future_provider_field": {"nested": 1}},
    )
    assert classified == {
        "observed": ("bezeichnung",),
        "unknown": ("future_provider_field",),
    }


def test_full_source_hash_changes_for_late_unknown_field_and_identity_does_not():
    before = property_period_evidence(period_dto(late={"v": 1}), "run-a")
    after = property_period_evidence(period_dto(late={"v": 2}), "run-b")

    assert before.identity == after.identity
    assert before.identity.token == after.identity.token
    assert before.source_sha256 != after.source_sha256
    assert before.private_source_copy()["late_provider_extension"] == {"v": 1}


def test_explicit_mappings_cover_property_period_unit_and_user_without_names():
    prop = property_identity(41)
    period = period_identity(41, 7)
    user = TehaOrderUser(
        user_id=601,
        unit_id=501,
        sequence_number="03",
        _source={
            "id": 601,
            "neId": 501,
            "lfdNr": "03",
            "bewohnerName": "not-an-identity-key",
            "future_user_field": {"kept": True},
        },
    )
    evidence = order_user_evidence(
        user,
        "run-users",
        termin_id=9001,
        lieg_nr="SYNTHETIC-LIEG-41",
        property_key=prop,
    )

    complete = classify_preview(evidence, mappings())
    missing = classify_preview(evidence, mappings(include_user=False))

    assert complete.state == "new"
    assert missing.state == "conflicting"
    assert missing.reasons == ("mapping_required",)
    assert evidence.private_source_copy()["future_user_field"] == {"kept": True}
    assert {requirement.target_kind for requirement in evidence.requirements} == {
        "property",
        "unit",
        "tenant",
    }
    assert period.token != prop.token


def test_preview_new_unchanged_changed_and_mapping_generation_conflict():
    evidence = property_period_evidence(period_dto(late={"revision": 1}), "run-1")
    index = mappings(generation=1)
    new = classify_preview(evidence, index)
    assert new.state == "new"
    mapped = mapping_digest(evidence, index)

    prior = PriorReceipt(
        identity_token=evidence.identity.token,
        mapping_sha256=mapped,
        source_sha256=evidence.source_sha256,
        content_sha256=None,
    )
    same = classify_preview(evidence, index, prior)
    changed = classify_preview(
        property_period_evidence(period_dto(late={"revision": 2}), "run-2"),
        index,
        prior,
    )
    remapped = classify_preview(evidence, mappings(generation=2), prior)

    assert same.state == "unchanged"
    assert changed.state == "changed"
    assert remapped.state == "conflicting"
    assert remapped.reasons == ("mapping_generation_changed",)


def test_document_requires_all_explicit_relations_and_preserves_original_hash():
    prop = property_identity(41)
    period = period_identity(41, 7)
    unit = unit_identity("SYNTHETIC-LIEG-41", 501)
    user = user_identity(9001, 601)
    content = content_dto()
    evidence = document_evidence(
        document_dto(late={"unknown": ["kept", 3]}),
        "run-document",
        property_key=prop,
        period_key=period,
        unit_key=unit,
        user_key=user,
        content=content,
    )

    missing_user = MappingIndex(
        [
            ExplicitMapping(prop, "property", "property-local"),
            ExplicitMapping(period, "billing_period", "period-local"),
            ExplicitMapping(unit, "unit", "unit-local"),
        ]
    )
    assert classify_preview(evidence, missing_user).state == "conflicting"

    decision = classify_preview(evidence, mappings())
    projection = document_projection(
        evidence,
        decision,
        property_id="property-local",
        unit_id="unit-local",
        title="Explicit synthetic TEHA document",
    )

    assert projection.expected_content_sha256 == content.sha256
    assert projection.expected_content_size == len(content.content)
    assert projection.document.property_id == "property-local"
    assert projection.document.unit_id == "unit-local"
    assert projection.document.contract_id is None
    assert "display-name.pdf" not in projection.document.file_url
    assert "unknown" not in projection.document.description
    assert evidence.private_source_copy()["late_document_extension"] == {
        "unknown": ["kept", 3]
    }


def test_technical_order_projection_is_open_and_never_infers_provider_completion():
    evidence = technical_order_evidence(
        order_dto(late={"provider_closed": True}),
        "run-order",
        property_key=property_identity(41),
        period_key=period_identity(41, 7),
    )
    decision = classify_preview(evidence, mappings())
    projection = task_projection(
        evidence,
        decision,
        property_id="property-local",
        unit_id="unit-local",
        title="Explicit local technical follow-up",
        due_date=None,
    )

    assert projection.task.status == "open"
    assert projection.task.property_id == "property-local"
    assert projection.task.unit_id == "unit-local"
    assert "synthetic-provider-status" not in (projection.task.description or "")
    assert "provider_closed" not in (projection.task.description or "")


def test_resume_cursor_goes_well_past_10000_without_total_inventory_cap():
    run_id = "run-large"
    source_sha = hashlib.sha256(b"immutable synthetic source").hexdigest()
    cursor = ResumeCursor(run_id, source_sha, 10_000)
    packet, next_cursor = receive_batch(
        (index for index in range(12_345)),
        history_run_id=run_id,
        source_sha256=source_sha,
        cursor=cursor,
        batch_size=7,
    )

    assert packet == tuple(range(10_000, 10_007))
    assert next_cursor == ResumeCursor(run_id, source_sha, 10_007)

    with pytest.raises(ValueError, match="another immutable source"):
        receive_batch(
            range(20_000),
            history_run_id=run_id,
            source_sha256=hashlib.sha256(b"changed").hexdigest(),
            cursor=cursor,
            batch_size=3,
        )


@pytest.fixture
def sqlite_history(tmp_path):
    with journal_engine(tmp_path, "sqlite") as engine:
        ring = IBANKeyring("synthetic", {"synthetic": generate_key()})
        store = SQLIntegrationHistoryStore(sessionmaker(engine), keyring=ring)
        yield store


def login_payload():
    return {
        "error": None,
        "accessToken": ACCESS,
        "refreshToken": REFRESH,
        "id": 17,
        "mandantId": 1,
        "name": "synthetic-profile",
    }


def transport_for(handler):
    def dispatch(request):
        if request.url.path == "/api/user":
            return httpx.Response(200, json=login_payload())
        return handler(request)

    return TehaTransport(transport=httpx.MockTransport(dispatch))


def test_journaled_read_preserves_complete_unknown_exchange_and_omits_credentials(
    sqlite_history,
):
    response = {
        "success": True,
        "liegenschaften": [
            period_source(late={"after_known_fields": [None, 42]})
        ],
        "future_top_level": {"retained": True},
    }
    with transport_for(lambda request: httpx.Response(200, json=response)) as transport:
        reader = JournaledTehaReader(transport, sqlite_history, ACTOR)
        authentication = reader.authenticate("synthetic-user", PASSWORD)
        received = reader.list_property_periods()

    auth_detail = sqlite_history.detail("teha", authentication.run_id, ACTOR)
    accepted = auth_detail["observations"][0]["artifacts"]["request"]
    encoded = repr(accepted)
    assert PASSWORD not in encoded
    assert "synthetic-user" not in encoded
    assert accepted["payload"]["arguments"] == {"credentials": "omitted"}

    detail = sqlite_history.detail("teha", received.run_id, ACTOR)
    exchange = history_exchange(detail, expected_operation="list_property_periods")
    assert exchange["response"]["body"]["future_top_level"] == {"retained": True}
    assert exchange["response"]["body"]["liegenschaften"][0][
        "late_provider_extension"
    ] == {"after_known_fields": [None, 42]}
    assert detail["history_status"] == "completed"
    assert len(received.value) == 1


def test_mid_read_network_error_is_uncertain_and_never_retried(sqlite_history):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError(
            "synthetic private network detail must not be persisted",
            request=request,
        )

    with transport_for(handler) as transport:
        transport.authenticate("synthetic-user", PASSWORD)
        reader = JournaledTehaReader(transport, sqlite_history, ACTOR)
        with pytest.raises(TehaError) as failure:
            reader.list_property_periods()

    assert failure.value.code == "provider_network_error"
    assert calls == 1
    page = sqlite_history.page("teha", ACTOR, state="outcome_uncertain")
    assert len(page["items"]) == 1
    detail = sqlite_history.detail("teha", page["items"][0]["id"], ACTOR)
    terminal = detail["observations"][-1]["artifacts"]["response"]
    assert terminal["success"] is False
    assert terminal["details"]["automatic_retry"] is False
    assert terminal["details"]["error"]["code"] == "provider_network_error"
    assert "private network detail" not in repr(detail)


def test_success_is_not_returned_when_terminal_exchange_cannot_be_journaled(tmp_path):
    with journal_engine(tmp_path, "sqlite") as engine:
        ring = IBANKeyring("synthetic", {"synthetic": generate_key()})
        small = SQLIntegrationHistoryStore(
            sessionmaker(engine),
            keyring=ring,
            limits=HistoryLimits(
                artifact_bytes=8 * 1024,
                page_bytes=64 * 1024,
                temp_bytes=128 * 1024,
                timeout_seconds=10,
            ),
        )
        response = {
            "success": True,
            "liegenschaften": [
                period_source(late={"large": "x" * 24_000})
            ],
        }
        transport = transport_for(lambda request: httpx.Response(200, json=response))
        transport.authenticate("synthetic-user", PASSWORD)
        reader = JournaledTehaReader(transport, small, ACTOR)

        with pytest.raises(HistoryError, match="HISTORY_BUDGET_EXCEEDED"):
            reader.list_property_periods()

        assert transport.authenticated is False
        page = small.page("teha", ACTOR, state="pending")
        assert len(page["items"]) == 1
        assert page["items"][0]["history_status"] == "outcome_unconfirmed"


def test_document_read_history_keeps_unknown_envelope_but_not_base64_pdf(sqlite_history):
    document_bytes = b"%PDF-1.4\nsynthetic private TEHA bytes\n%%EOF\n"
    encoded = __import__("base64").b64encode(document_bytes).decode("ascii")
    response = {
        "success": True,
        "content": encoded,
        "future_document_envelope": {"late": [None, 7]},
    }

    def handler(request):
        assert request.url.path == "/api/Liegenschaften/document-content"
        return httpx.Response(200, json=response)

    with transport_for(handler) as transport:
        transport.authenticate("synthetic-user", PASSWORD)
        reader = JournaledTehaReader(transport, sqlite_history, ACTOR)
        received = reader.read_document("SYNTHETIC-LIEG-41", "opaque-ref-1")

    assert received.value.content == document_bytes
    assert received.value.sha256 == hashlib.sha256(document_bytes).hexdigest()
    detail = sqlite_history.detail("teha", received.run_id, ACTOR)
    exchange = history_exchange(detail, expected_operation="read_document")
    body = exchange["response"]["body"]
    assert body["future_document_envelope"] == {"late": [None, 7]}
    assert body["content"] == {
        "omitted": "document_bytes",
        "sha256": received.value.sha256,
        "size_bytes": len(document_bytes),
        "media_type": "application/pdf",
    }
    assert encoded not in repr(detail)


def test_field_manifest_router_is_local_value_free_and_explicitly_admin_bound(monkeypatch):
    user = {
        "id": "synthetic-admin",
        "role": "eigentuemer",
        "is_active": True,
        "portfolio_access": "all",
        "portfolio_ids": [],
    }
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: user if identifier == user["id"] else None)
    app = FastAPI()
    app.include_router(teha_router.router)
    app.dependency_overrides[teha_router._require_teha_administration] = lambda: None
    scope = scope_from_user(user)

    @app.middleware("http")
    async def install_scope(request, call_next):
        with scope_context(scope):
            return await call_next(request)

    client = TestClient(app)
    token = create_access_token("synthetic-admin")
    response = client.get(
        "/integrations/teha/field-manifest",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"].startswith("teha-observed-fields/")
    assert body["policy"]["values_are_not_in_manifest"] is True
    serialized = repr(body)
    for private_value in (
        "SYNTHETIC-LIEG-41",
        "synthetic-user",
        PASSWORD,
        ACCESS,
        REFRESH,
    ):
        assert private_value not in serialized
