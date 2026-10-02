"""Wohnungsgeberbestätigung: reviewed facts, immutable originals and replay."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
from io import BytesIO
from threading import Event, current_thread
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend import auth
from backend.auth import require_auth
from backend.db.contract_wizard_models import ContractDraftORM
from backend.db.document_version_models import (
    DocumentVersionORM,
    ensure_document_version_schema,
)
from backend.dependencies import get_store
from backend.models import ContractPatch, DocumentPatch, PropertyCreate, TenantCreate
from backend.routers import files as files_router
from backend.routers.housing_confirmations import router as housing_router
from backend.services import document_versions
from backend.services import housing_confirmation as service
from backend.services.document_version_types import VersionCommand
from backend.services.document_version_validation import _verify_document_versions
from backend.services.housing_confirmation_types import (
    CertificateData,
    CorrectionReference,
    PreviewRequest,
    SaveRequest,
    SourceEtags,
)
from backend.services.housing_confirmation_validation import (
    HousingConfirmationValidationError,
    validate_housing_confirmation_snapshot,
)
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.recovery_archive import RecoveryError
from backend.services.tenant_privacy import (
    anonymize_tenant_profile,
    export_tenant_metadata,
    preview_tenant_anonymization,
)
from backend.storage import NotFoundError, ValidationError
from backend.tests.test_contract_lifecycle import active as active


@pytest.fixture
def housing(active):
    if active.engine is not None:
        with active.engine.begin() as connection:
            ensure_document_version_schema(connection)
    prop = active.store.get_property(active.property.id)
    active.property = active.store.update_property(
        prop.id,
        PropertyCreate(
            portfolio_id=prop.portfolio_id,
            name=prop.name,
            property_type=prop.property_type,
            status=prop.status,
            year_built=prop.year_built,
            living_area_sqm=prop.living_area_sqm,
            usable_area_sqm=prop.usable_area_sqm,
            plot_area_sqm=prop.plot_area_sqm,
            ownership_share=prop.ownership_share,
            purchase_price=prop.purchase_price,
            purchase_date=prop.purchase_date,
            market_value=prop.market_value,
            valuation_date=prop.valuation_date,
            address_line="Musterstraße 17",
            postal_code="66111",
            city="Saarbrücken",
            country="Deutschland",
        ),
    )
    return active


def source(box, actor="actor"):
    return service.source(box.store, box.contract.id, actor)


def preview_payload(box, **changes):
    current = source(box)
    values = {
        "housing_provider_name": "Verwaltung ÄÖÜ GmbH",
        "housing_provider_address": "Lange Straße 5\n66111 Saarbrücken",
        "owner_same_as_provider": False,
        "owner_name": "Eigentümerin Élodie Beispiel",
        "move_in_date": date(2026, 2, 3),
        "issue_date": date(2026, 10, 2),
        "apartment_address": "Musterstraße 17\n66111 Saarbrücken",
        "apartment_label": "Wohnung A",
        "issuer_name": "Beauftragte Person",
        "issuer_role": "authorized_person",
        "residents": [
            "Synthetic tenant",
            "Zoë Beispiel",
            "Łukasz Beispiel",
        ],
    }
    values.update(changes)
    return PreviewRequest(
        data=CertificateData(**values),
        source_etags=SourceEtags(**current["source_etags"]),
    )


def reviewed(box, **changes):
    payload = preview_payload(box, **changes)
    result = service.preview(box.store, box.contract.id, payload, "actor")
    return payload, result


def save_payload(payload, review, *, key="housing-save"):
    return SaveRequest(
        **payload.model_dump(),
        idempotency_key=key,
        review_hash=review["review_hash"],
        confirmed_actual_move_in=True,
        confirmed_authority=True,
        confirmed_residents=True,
    )


def version_rows(box):
    if box.db is not None:
        box.db.expire_all()
        return list(box.db.scalars(select(DocumentVersionORM)))
    return list(
        box.store.__dict__.get(DocumentVersionORM.__tablename__, {}).values()
    )


def test_source_keeps_actual_move_in_manual_and_tenant_only_suggestion(housing):
    result = source(housing)

    assert result["suggestions"]["apartment_address"] == (
        "Musterstraße 17\n66111 Saarbrücken\nDeutschland"
    )
    assert result["suggestions"]["resident_names"] == ["Synthetic tenant"]
    assert result["suggestions"]["actual_move_in_date"] is None
    assert result["suggestions"]["contract_start_date_for_reference"] == "2026-01-01"
    assert result["policy"] == {
        "main_tenant_is_suggestion_only": True,
        "contract_start_is_not_actual_move_in": True,
        "handover_date_is_not_actual_move_in": True,
        "additional_residents_require_explicit_input": True,
    }


def test_preview_publish_replay_archives_exact_pdf_without_finance_side_effects(housing):
    payload, review = reviewed(housing)
    preview_bytes, preview_sha, preview_hash = service.preview_pdf(
        housing.store, housing.contract.id, payload, "actor"
    )
    assert preview_bytes.startswith(b"%PDF-")
    assert hashlib.sha256(preview_bytes).hexdigest() == preview_sha
    assert preview_hash == review["review_hash"]
    assert payload.data.move_in_date != housing.contract.start_date

    before_cash = {
        "bookings": len(housing.store.list_bookings()),
        "payments": len(housing.store.list_payments()),
        "receivables": len(housing.store.list_receivables()),
        "rent_charges": len(housing.store.list_rent_charges()),
    }
    command = save_payload(payload, review)
    published = service.publish(
        housing.store, housing.contract.id, command, "actor"
    )
    replay = service.publish(
        housing.store, housing.contract.id, command, "actor"
    )

    assert replay == published
    assert published["data"]["residents"][-1] == "Łukasz Beispiel"
    assert published["signature_recorded"] is False
    assert published["authority_transmission_recorded"] is False
    assert len(version_rows(housing)) == 1
    assert {
        "bookings": len(housing.store.list_bookings()),
        "payments": len(housing.store.list_payments()),
        "receivables": len(housing.store.list_receivables()),
        "rent_charges": len(housing.store.list_rent_charges()),
    } == before_cash

    key = published["file_url"].removeprefix("/uploads/")
    archived = service.read_pdf_for_key(housing.store, key, "actor")
    assert archived == preview_bytes
    compiled, _ = service.prepare_download(
        housing.store,
        housing.contract.id,
        published["document_id"],
        "actor",
    )
    try:
        assert compiled.path.read_bytes() == preview_bytes
        assert compiled.manifest["sha256"] == preview_sha
    finally:
        compiled.close()

    changed = command.model_copy(
        update={
            "data": command.data.model_copy(
                update={"issuer_name": "Andere ausstellende Person"}
            )
        }
    )
    with pytest.raises(HTTPException) as failure:
        service.publish(
            housing.store, housing.contract.id, changed, "actor"
        )
    assert failure.value.status_code == 409
    assert len(version_rows(housing)) == 1


def test_source_change_after_preview_is_412_and_writes_nothing(housing):
    payload, review = reviewed(housing)
    tenant = housing.store.get_tenant(housing.tenant.id)
    housing.store.update_tenant(
        tenant.id,
        TenantCreate(
            **{
                **tenant.model_dump(
                    exclude={"id", "created_at", "updated_at"}
                ),
                "full_name": "Synthetic tenant renamed",
            }
        ),
    )

    with pytest.raises(HTTPException) as failure:
        service.publish(
            housing.store,
            housing.contract.id,
            save_payload(payload, review, key="stale-source"),
            "actor",
        )
    assert failure.value.status_code == 412
    assert version_rows(housing) == []
    assert [
        document
        for document in housing.store.list_documents()
        if document.document_type == "housing_confirmation"
    ] == []


def test_correction_creates_new_original_and_old_bytes_remain_unchanged(housing):
    first_payload, first_review = reviewed(housing)
    first = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(first_payload, first_review, key="first-original"),
        "actor",
    )
    first_bytes = service.read_pdf_for_key(
        housing.store,
        first["file_url"].removeprefix("/uploads/"),
        "actor",
    )

    correction = CorrectionReference(
        document_id=first["document_id"],
        version_id=first["version_id"],
    )
    second_preview_request = PreviewRequest(
        data=first_payload.data.model_copy(
            update={"residents": [*first_payload.data.residents, "Neue Person"]}
        ),
        source_etags=first_payload.source_etags,
        correction_of=correction,
    )
    second_review = service.preview(
        housing.store,
        housing.contract.id,
        second_preview_request,
        "actor",
    )
    second = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(
            second_preview_request,
            second_review,
            key="corrected-original",
        ),
        "actor",
    )

    assert second["document_id"] != first["document_id"]
    assert second["correction_of"]["document_id"] == first["document_id"]
    assert len(version_rows(housing)) == 2
    assert (
        service.read_pdf_for_key(
            housing.store,
            first["file_url"].removeprefix("/uploads/"),
            "actor",
        )
        == first_bytes
    )


def test_list_uses_cursor_and_returns_full_archived_review_data(housing):
    payload, review = reviewed(housing)
    first = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(payload, review, key="list-1"),
        "actor",
    )
    second_payload = preview_payload(
        housing,
        residents=["Synthetic tenant", "Zweite Person"],
    )
    second_review = service.preview(
        housing.store, housing.contract.id, second_payload, "actor"
    )
    second = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(second_payload, second_review, key="list-2"),
        "actor",
    )

    page1 = service.listing(
        housing.store, housing.contract.id, "actor", limit=1
    )
    assert len(page1["items"]) == 1
    assert page1["has_more"] is True
    assert page1["next_cursor"]
    page2 = service.listing(
        housing.store,
        housing.contract.id,
        "actor",
        limit=1,
        after=page1["next_cursor"],
    )
    assert len(page2["items"]) == 1
    assert page2["has_more"] is False
    assert {
        page1["items"][0]["document_id"],
        page2["items"][0]["document_id"],
    } == {first["document_id"], second["document_id"]}
    assert all(item["data"]["residents"] for item in [*page1["items"], *page2["items"]])


def test_tampered_feature_metadata_is_rejected_without_claiming_valid_original(housing):
    payload, review = reviewed(housing)
    published = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(payload, review, key="tamper-proof"),
        "actor",
    )
    row = version_rows(housing)[0]
    snapshot = deepcopy(row.metadata_snapshot)
    snapshot["housing_confirmation"]["review"]["data"]["residents"][0] = "Manipulated"

    broken = SimpleNamespace(
        **{
            column.name: getattr(row, column.name)
            for column in row.__table__.columns
        }
    )
    broken.metadata_snapshot = snapshot
    with pytest.raises(HousingConfirmationValidationError):
        validate_housing_confirmation_snapshot(
            broken, broken.metadata_snapshot
        )

    assert (
        service.read_pdf_for_key(
            housing.store,
            published["file_url"].removeprefix("/uploads/"),
            "actor",
        )
        is not None
    )


def test_pdf_handles_many_unicode_residents_without_fixed_person_limit(housing):
    residents = [
        f"Person {index:02d} ÄÖÜ é č Ł – SehrLangerFamilienname"
        for index in range(1, 46)
    ]
    payload = preview_payload(
        housing,
        residents=residents,
        housing_provider_address=(
            "Sehr lange synthetische Anschrift mit Zusatz und Gebäudeteil\n"
            "Musterallee 123 A, Hinterhaus, 4. Obergeschoss\n"
            "66111 Saarbrücken, Deutschland"
        ),
    )
    pdf, sha256, _ = service.preview_pdf(
        housing.store, housing.contract.id, payload, "actor"
    )

    assert pdf.startswith(b"%PDF-")
    assert hashlib.sha256(pdf).hexdigest() == sha256
    assert len(pdf) > 5000
    # The reviewed source is authoritative even when PDF text extraction is
    # unavailable in the test environment.
    review = service.preview(
        housing.store, housing.contract.id, payload, "actor"
    )
    assert review["review"]["data"]["residents"] == residents


def test_offline_document_version_validator_accepts_published_housing_original(housing):
    if housing.engine is None:
        pytest.skip("offline SQL validator gate")
    payload, review = reviewed(housing)
    service.publish(
        housing.store,
        housing.contract.id,
        save_payload(payload, review, key="offline-proof"),
        "actor",
    )
    with housing.engine.connect() as connection:
        assert _verify_document_versions(connection) == 1


def test_http_auth_notfound_and_validation_boundaries(housing):
    app = FastAPI()
    app.include_router(housing_router)
    actor = SimpleNamespace(id="actor")
    app.dependency_overrides[get_store] = lambda: housing.store
    app.dependency_overrides[require_auth] = lambda: actor
    client = TestClient(app)

    source_response = client.get(
        f"/contracts/{housing.contract.id}/housing-confirmations/source"
    )
    assert source_response.status_code == 200
    assert source_response.json()["suggestions"]["actual_move_in_date"] is None

    missing = client.get(
        "/contracts/00000000-0000-0000-0000-000000000000/housing-confirmations/source"
    )
    assert missing.status_code == 404

    payload = preview_payload(housing)
    invalid = payload.model_dump(mode="json")
    invalid["data"]["residents"] = []
    rejected = client.post(
        f"/contracts/{housing.contract.id}/housing-confirmations/preview",
        json=invalid,
    )
    assert rejected.status_code == 422

    review = service.preview(housing.store, housing.contract.id, payload, "actor")
    command = save_payload(payload, review, key="readonly-denied")
    actor.id = "readonly"
    denied = client.post(
        f"/contracts/{housing.contract.id}/housing-confirmations",
        json=command.model_dump(mode="json"),
    )
    assert denied.status_code == 403
    assert version_rows(housing) == []

    actor.id = "actor"
    unconfirmed = command.model_dump(mode="json")
    unconfirmed["confirmed_authority"] = False
    missing_confirmation = client.post(
        f"/contracts/{housing.contract.id}/housing-confirmations",
        json=unconfirmed,
    )
    assert missing_confirmation.status_code == 422
    assert version_rows(housing) == []

    def unauthenticated():
        raise HTTPException(401, "login required")

    app.dependency_overrides[require_auth] = unauthenticated
    unauthorized = client.get(
        f"/contracts/{housing.contract.id}/housing-confirmations/source"
    )
    assert unauthorized.status_code == 401


def test_reserved_virtual_key_ignores_unrelated_physical_shadow(housing, monkeypatch):
    payload, review = reviewed(housing)
    published = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(payload, review, key="reserved-key"),
        "actor",
    )
    key = published["file_url"].removeprefix("/uploads/")
    expected = service.read_pdf_for_key(housing.store, key, "actor")

    class ShadowStorage:
        def get(self, requested):
            assert requested == key
            return b"%PDF-physical-shadow-must-never-win"

    import backend.dependencies as dependencies

    monkeypatch.setattr(dependencies, "store", housing.store)
    monkeypatch.setattr(files_router, "get_file_storage", lambda: ShadowStorage())
    scope = scope_from_user(housing.users["actor"])
    with scope_context(scope):
        response = files_router.download_file(key=key)

    assert response.body == expected
    assert response.body != b"%PDF-physical-shadow-must-never-win"


def test_source_reuses_exact_published_contract_wizard_landlord_fields(housing):
    stamp = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    row = ContractDraftORM(
        id="wizard-source-confirmation",
        portfolio_id=housing.p.id,
        actor_id="actor",
        create_key="wizard-source",
        create_hash="a" * 64,
        data={
            "property_id": housing.property.id,
            "unit_id": housing.unit.id,
            "tenant_id": housing.tenant.id,
            "landlord_name": "Vermieterin Quelle GmbH",
            "landlord_address": "Quellstraße 9\n66111 Saarbrücken",
        },
        revision=7,
        state="committed",
        review={"synthetic": True},
        review_hash="b" * 64,
        pdf=b"%PDF-synthetic",
        pdf_sha256="c" * 64,
        contract_id=housing.contract.id,
        document_id=None,
        published_tenant_id=housing.tenant.id,
        created_at=stamp,
        updated_at=stamp,
    )
    if housing.db is not None:
        housing.db.add(row)
        housing.db.commit()
    else:
        housing.store.__dict__.setdefault(
            ContractDraftORM.__tablename__, {}
        )[row.id] = row

    result = source(housing)

    assert result["suggestions"]["housing_provider_name"] == "Vermieterin Quelle GmbH"
    assert result["suggestions"]["housing_provider_address"] == (
        "Quellstraße 9\n66111 Saarbrücken"
    )
    assert result["source"]["wizard"]["id"] == row.id
    assert result["source_etags"]["wizard_revision"]


def test_failure_after_original_chunks_rolls_back_document_and_can_retry(
    housing, monkeypatch
):
    payload, review = reviewed(housing)
    command = save_payload(payload, review, key="rollback-after-chunks")
    original = service.document_versions.persist_version_bytes

    def fail_after_persist(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure after persisted original")

    monkeypatch.setattr(
        service.document_versions,
        "persist_version_bytes",
        fail_after_persist,
    )
    with pytest.raises(RuntimeError, match="after persisted original"):
        service.publish(
            housing.store, housing.contract.id, command, "actor"
        )

    assert version_rows(housing) == []
    assert [
        document
        for document in housing.store.list_documents()
        if document.document_type == "housing_confirmation"
    ] == []

    monkeypatch.setattr(
        service.document_versions,
        "persist_version_bytes",
        original,
    )
    published = service.publish(
        housing.store, housing.contract.id, command, "actor"
    )
    assert published["version_id"]
    assert len(version_rows(housing)) == 1


def test_foreign_scope_and_revoked_write_rights_publish_nothing(housing):
    with pytest.raises((HTTPException, NotFoundError)) as foreign:
        service.source(
            housing.store, housing.contract.id, "foreign"
        )
    if isinstance(foreign.value, HTTPException):
        assert foreign.value.status_code in {403, 404}

    payload, review = reviewed(housing)
    previous_role = housing.users["actor"]["role"]
    housing.users["actor"]["role"] = "readonly"
    try:
        with pytest.raises(HTTPException) as denied:
            service.publish(
                housing.store,
                housing.contract.id,
                save_payload(payload, review, key="revoked-right"),
                "actor",
            )
        assert denied.value.status_code == 403
    finally:
        housing.users["actor"]["role"] = previous_role
    assert version_rows(housing) == []


def test_sqlite_memory_account_fence_covers_actual_housing_commit(housing, monkeypatch):
    if housing.engine is None:
        pytest.skip("Actual SQLite/Memory-auth outer commit required")
    accounts = auth.InMemoryUserStore()
    for identifier, user in housing.users.items():
        accounts.create({**user, "username": "housing-fence-" + identifier,
                         "email": identifier + "@example.invalid",
                         "hashed_password": "unused-synthetic-hash"})
    monkeypatch.setattr(auth, "_user_store", accounts)
    monkeypatch.setattr(auth, "get_user_by_id", accounts.get_by_id)
    payload, review = reviewed(housing)
    command = save_payload(payload, review, key="native-account-fence")
    held, release, contended = Event(), Event(), Event()

    def before_commit(_connection):
        if current_thread().name.startswith("housing-outer-commit"):
            held.set()
            assert release.wait(10)

    def revoke():
        available = accounts._lock.acquire(blocking=False)
        if available:
            accounts._lock.release()
        try:
            assert not available, "Account change entered the housing SQL commit window"
        finally:
            contended.set()
        result = accounts.update("actor", {"is_active": False, "portfolio_access": "all", "portfolio_ids": []})
        # The management change must become visible after the original's
        # actual independent database transaction has committed.
        with Session(housing.engine) as session:
            assert session.scalar(select(DocumentVersionORM.id)) is not None
        return result

    event.listen(housing.engine, "commit", before_commit)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="housing-outer-commit") as writers:
            publication = writers.submit(service.publish, housing.store, housing.contract.id, command, "actor")
            try:
                assert held.wait(10)
                with ThreadPoolExecutor(max_workers=1) as managers:
                    revocation = managers.submit(revoke)
                    try:
                        assert contended.wait(10)
                    finally:
                        release.set()
                    assert revocation.result(timeout=10)["is_active"] is False
            finally:
                release.set()
            assert publication.result(timeout=10)["document_id"]
    finally:
        release.set()
        event.remove(housing.engine, "commit", before_commit)
    assert len(version_rows(housing)) == 1
    with pytest.raises(HTTPException) as denied:
        service.publish(housing.store, housing.contract.id, command, "actor")
    assert denied.value.status_code == 401


def test_profile_anonymization_keeps_housing_original_and_discloses_retained_names(
    housing,
):
    payload, review = reviewed(
        housing,
        residents=[
            "Synthetic tenant",
            "Retained Household Person",
        ],
    )
    published = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(payload, review, key="privacy-retained"),
        "actor",
    )
    key = published["file_url"].removeprefix("/uploads/")
    original = service.read_pdf_for_key(
        housing.store, key, "actor"
    )

    housing.store._patch_entity(
        "contract",
        housing.contract.id,
        ContractPatch(status="terminated"),
    )
    scope = scope_from_user(housing.users["actor"])
    with scope_context(scope):
        before = export_tenant_metadata(
            housing.store, housing.tenant.id
        )
        plan = preview_tenant_anonymization(
            housing.store, housing.tenant.id
        )
        assert (
            plan["retained_personal_evidence"]["document_versions"]["count"]
            >= 1
        )
        result = anonymize_tenant_profile(
            housing.store,
            housing.tenant.id,
            plan_hash=plan["plan_hash"],
            confirm_tenant_id=housing.tenant.id,
        )
        after = export_tenant_metadata(
            housing.store, housing.tenant.id
        )

    assert result["status"] == "profile_anonymized"
    retained = [
        row
        for row in after["document_versions"]
        if row["id"] == published["version_id"]
    ]
    assert len(retained) == 1
    evidence = retained[0]["metadata_snapshot"]["housing_confirmation"]
    assert (
        "Retained Household Person"
        in evidence["review"]["data"]["residents"]
    )
    assert service.read_pdf_for_key(
        housing.store, key, "actor"
    ) == original
    assert before["document_versions"] == after["document_versions"]


def test_live_document_metadata_edits_do_not_rewrite_archived_certificate_identity(housing):
    payload, review = reviewed(housing)
    command = save_payload(payload, review, key="metadata-edit")
    published = service.publish(
        housing.store, housing.contract.id, command, "actor"
    )
    before = service.read_pdf_for_key(
        housing.store,
        published["file_url"].removeprefix("/uploads/"),
        "actor",
    )
    document = housing.store.get_document(published["document_id"])
    housing.store._patch_entity(
        "document",
        document.id,
        DocumentPatch(
            title="Harmlos geänderter Anzeigename",
            document_type="other_display_category",
            description="Nur aktuelle Metadaten geändert",
        ),
    )

    replay = service.publish(
        housing.store, housing.contract.id, command, "actor"
    )
    page = service.listing(
        housing.store, housing.contract.id, "actor", limit=25
    )
    compiled, _ = service.prepare_download(
        housing.store,
        housing.contract.id,
        published["document_id"],
        "actor",
    )
    try:
        assert replay == published
        assert [item["document_id"] for item in page["items"]] == [
            published["document_id"]
        ]
        assert compiled.path.read_bytes() == before
    finally:
        compiled.close()
    assert (
        service.read_pdf_for_key(
            housing.store,
            published["file_url"].removeprefix("/uploads/"),
            "actor",
        )
        == before
    )
    row = version_rows(housing)[0]
    assert row.metadata_snapshot["document_type"] == "housing_confirmation"
    assert row.metadata_snapshot["title"] != "Harmlos geänderter Anzeigename"


def test_generic_document_version_upload_cannot_replace_housing_correction_flow(housing):
    payload, review = reviewed(housing)
    published = service.publish(
        housing.store,
        housing.contract.id,
        save_payload(payload, review, key="no-generic-version"),
        "actor",
    )
    document = housing.store.get_document(published["document_id"])
    command = VersionCommand(
        idempotency_key="forbidden-generic-upload",
        expected_document_etag=document_versions.etag(
            "documents", document.id, document.updated_at
        ),
        expected_head_id=published["version_id"],
        comment="Synthetic generic replacement attempt",
        confirmed=True,
    )

    with pytest.raises(ValidationError, match="eigenen geprüften Ablauf"):
        document_versions.publish(
            housing.store,
            document.id,
            command,
            "actor",
            source=BytesIO(b"%PDF-1.4\nsynthetic replacement\n%%EOF\n"),
            upload_name="replacement.pdf",
        )

    assert len(version_rows(housing)) == 1
    assert service.listing(
        housing.store, housing.contract.id, "actor"
    )["items"][0]["version_id"] == published["version_id"]


def test_offline_validator_rejects_corrupt_housing_extension_before_recovery_use(
    housing, tmp_path
):
    if housing.engine is None:
        pytest.skip("offline SQL corruption gate")
    payload, review = reviewed(housing)
    service.publish(
        housing.store,
        housing.contract.id,
        save_payload(payload, review, key="offline-corrupt"),
        "actor",
    )

    # Corrupt only an offline copy, as a damaged/restored source image could be
    # presented after the live immutable triggers no longer protect it.
    source_path = housing.engine.url.database
    target_path = tmp_path / "housing-corrupt-offline.sqlite"
    before = sqlite3.connect(source_path)
    corrupt = sqlite3.connect(target_path)
    try:
        before.backup(corrupt)
        trigger_names = [
            row[0]
            for row in corrupt.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name='document_versions'"
            )
        ]
        for name in trigger_names:
            escaped = name.replace('"', '""')
            corrupt.execute(f'DROP TRIGGER "{escaped}"')
        row = corrupt.execute(
            "SELECT id, metadata_snapshot FROM document_versions LIMIT 1"
        ).fetchone()
        assert row is not None
        snapshot = json.loads(row[1])
        snapshot["housing_confirmation"]["review_hash"] = "0" * 64
        corrupt.execute(
            "UPDATE document_versions SET metadata_snapshot=? WHERE id=?",
            (
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                row[0],
            ),
        )
        corrupt.commit()

        with pytest.raises(RecoveryError):
            _verify_document_versions(corrupt)
    finally:
        before.close()
        corrupt.close()
