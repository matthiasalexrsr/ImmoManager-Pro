"""Wohnungsgeberbestätigung: reviewed facts, one immutable original, safe retry, correction."""

import hashlib
import os
from datetime import date
from typing import Any

import pytest
from archive_helpers import lease_with_document, purge_originals
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import auth
from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.document_version_models import install_guards
from backend.dependencies import store
from backend.paths import get_uploads_dir
from backend.services import document_versions as archive
from backend.services import housing_confirmation as service
from backend.services.data_snapshot import clear_business_data
from backend.services.document_version_validation import ArchiveIntegrityError, verify_document_versions

SQL = os.environ.get("TEST_STORE_BACKEND", "memory") == "sql"
shared: Any = store

RESIDENTS = ["Mia Muster", "Zoë Beispiel", "Łukasz Beispiel"]


@pytest.fixture
def owner():
    purge_originals(store)
    clear_business_data(store)
    clear_users()
    user = register_user("linda.reiser", "linda_reiser@web.de", "Linda Reiser", "Secret123", "eigentuemer")
    yield user
    purge_originals(store)
    clear_users()
    clear_business_data(store)


def _client(user) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {create_access_token(user.id)}"})


@pytest.fixture
def client(owner):
    return _client(owner)


@pytest.fixture
def lease(owner):
    return lease_with_document(store)


def _base(contract_id):
    return f"/api/v1/contracts/{contract_id}/housing-confirmations"


def _data(**changes):
    values = {
        "housing_provider_name": "Linda Reiser",
        "housing_provider_address": "Prießnitzstraße 4\n01099 Dresden",
        "owner_same_as_provider": True,
        "owner_name": None,
        "move_in_date": "2026-02-03",
        "issue_date": "2026-10-07",
        "apartment_address": "Bautzner Straße 61\n01099 Dresden",
        "apartment_label": "WE 3",
        "issuer_name": "Linda Reiser",
        "issuer_role": "housing_provider",
        "residents": RESIDENTS,
    }
    return {**values, **changes}


def _preview(client, contract_id, **changes):
    etags = client.get(_base(contract_id) + "/source").json()["source_etags"]
    payload = {"data": _data(**changes), "source_etags": etags}
    response = client.post(_base(contract_id) + "/preview", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


def _save(payload, review, key="wgb-1", **changes):
    return {**payload, "idempotency_key": key, "review_hash": review["review_hash"],
            "confirmed_actual_move_in": True, "confirmed_authority": True, "confirmed_residents": True, **changes}


def _publish(client, contract_id, key="wgb-1", **changes):
    payload, review = _preview(client, contract_id, **changes)
    response = client.post(_base(contract_id), json=_save(payload, review, key))
    assert response.status_code == 201, response.text
    return response.json()


def test_source_suggests_but_never_fills_in_the_actual_move_in(client, lease):
    body = client.get(_base(lease["contract"].id) + "/source").json()

    assert body["suggestions"]["actual_move_in_date"] is None
    assert body["suggestions"]["resident_names"] == ["Mia Muster"]
    assert body["suggestions"]["contract_start_date_for_reference"] == "2024-01-01"
    assert body["suggestions"]["apartment_address"] == "Bautzner Straße 61\n01099 Dresden"
    assert body["policy"]["contract_start_is_not_actual_move_in"] is True
    assert body["source"]["wizard"] is None and body["source_etags"]["wizard_revision"] is None


def test_preview_publish_and_retry_store_exactly_one_verified_original(client, lease):
    contract_id = lease["contract"].id
    payload, review = _preview(client, contract_id)
    pdf = client.post(_base(contract_id) + "/preview-pdf", json=payload)
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF-")
    assert pdf.headers["x-review-sha256"] == review["review_hash"]
    assert hashlib.sha256(pdf.content).hexdigest() == review["pdf_sha256"]

    first = client.post(_base(contract_id), json=_save(payload, review))
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["pdf_sha256"] == review["pdf_sha256"]
    assert result["data"]["residents"] == RESIDENTS and result["correction_of"] is None
    document = store.get_document(result["document_id"])
    assert document.document_type == "housing_confirmation" and document.contract_id == contract_id
    assert document.file_url == f"/uploads/housing-confirmations/{document.id}.pdf"

    # the answer got lost: the same command again returns the same original
    again = client.post(_base(contract_id), json=_save(payload, review))
    assert again.status_code == 201 and again.json()["version_id"] == result["version_id"]
    assert archive.count_originals(store, "contract", contract_id) == 1
    # the same key with other facts is refused
    other_payload, other_review = _preview(client, contract_id, move_in_date="2026-03-01")
    assert client.post(_base(contract_id), json=_save(other_payload, other_review)).status_code == 409

    stored = client.get(_base(contract_id) + f"/{document.id}/download")
    assert stored.content == pdf.content and stored.headers["x-content-sha256"] == review["pdf_sha256"]
    served = client.get(document.file_url)
    assert served.status_code == 200 and served.content == pdf.content
    assert served.headers["cache-control"] == "private, no-store"


def test_a_changed_source_or_review_writes_nothing(client, lease):
    contract_id = lease["contract"].id
    payload, review = _preview(client, contract_id)

    mismatch = client.post(_base(contract_id), json=_save(payload, {"review_hash": "0" * 64}))
    assert mismatch.status_code == 409
    unconfirmed = client.post(_base(contract_id), json=_save(payload, review, confirmed_residents=False))
    assert unconfirmed.status_code == 422
    assert client.patch(f"/api/v1/contracts/{contract_id}", json={"notes": "geändert"}).status_code == 200
    stale = client.post(_base(contract_id), json=_save(payload, review))
    assert stale.status_code == 412
    assert archive.count_originals(store, "contract", contract_id) == 0
    assert not [d for d in store.list_documents() if d.document_type == "housing_confirmation"]


def test_a_correction_is_a_new_original_and_the_first_stays_unchanged(client, lease):
    contract_id = lease["contract"].id
    first = _publish(client, contract_id)
    first_bytes = client.get(_base(contract_id) + f"/{first['document_id']}/download").content

    etags = client.get(_base(contract_id) + "/source").json()["source_etags"]
    payload = {"data": _data(residents=[*RESIDENTS, "Nachgetragene Person"]), "source_etags": etags,
               "correction_of": {"document_id": first["document_id"], "version_id": first["version_id"]}}
    review = client.post(_base(contract_id) + "/preview", json=payload).json()
    second = client.post(_base(contract_id), json=_save(payload, review, key="wgb-2")).json()

    assert second["document_id"] != first["document_id"]
    assert second["correction_of"] == {"document_id": first["document_id"], "version_id": first["version_id"]}
    assert client.get(_base(contract_id) + f"/{first['document_id']}/download").content == first_bytes

    page = client.get(_base(contract_id), params={"limit": 1}).json()
    assert page["has_more"] and len(page["items"]) == 1
    rest = client.get(_base(contract_id), params={"limit": 1, "after": page["next_cursor"]}).json()
    assert {page["items"][0]["document_id"], rest["items"][0]["document_id"]} == {
        first["document_id"], second["document_id"]}
    assert not rest["has_more"]
    assert client.get(_base(contract_id), params={"limit": 2, "after": page["next_cursor"]}).status_code == 422


def test_a_correction_must_belong_to_the_same_contract(client, lease):
    first = _publish(client, lease["contract"].id)
    other = lease_with_document(store, number="V-2", file_url="/uploads/documents/b.pdf")
    etags = client.get(_base(other["contract"].id) + "/source").json()["source_etags"]
    payload = {"data": _data(), "source_etags": etags,
               "correction_of": {"document_id": first["document_id"], "version_id": first["version_id"]}}

    assert client.post(_base(other["contract"].id) + "/preview", json=payload).status_code == 404


def test_many_residents_with_any_script_fit_on_following_pages(client, lease):
    residents = [f"Person {index:02d} – Zoë Łukasz Иван Μαρία" for index in range(1, 46)]
    result = _publish(client, lease["contract"].id, residents=residents)

    assert result["data"]["residents"] == residents
    pdfplumber = pytest.importorskip("pdfplumber")
    from io import BytesIO
    content = client.get(_base(lease["contract"].id) + f"/{result['document_id']}/download").content
    with pdfplumber.open(BytesIO(content)) as pdf:
        assert len(pdf.pages) >= 2
        text_all = "\n".join(page.extract_text() for page in pdf.pages)
    assert all(name in text_all for name in residents)


def test_only_roles_with_contract_and_document_rights_publish(client, lease, owner):
    contract_id = lease["contract"].id
    payload, review = _preview(client, contract_id)
    for role in ("buchhaltung", "techniker", "readonly"):
        user = register_user(f"u-{role}", f"{role}@example.com", role, "Secret123", role)
        refused = _client(user).post(_base(contract_id), json=_save(payload, review, key=f"k-{role}"))
        assert refused.status_code == 403, role
        assert _client(user).get(_base(contract_id) + "/source").status_code == 200   # reading is open
    manager = register_user("verwalter", "v@example.com", "Verwaltung", "Secret123", "verwalter")
    assert _client(manager).post(_base(contract_id), json=_save(payload, review, key="k-v")).status_code == 201

    # rights taken away after the preview: the publication is refused, nothing is written
    auth.update_user(manager.id, {"role": "techniker"})
    payload, review = _preview(client, contract_id, move_in_date="2026-04-01")
    with pytest.raises(Exception) as error:
        service.publish(store, contract_id, service.SaveRequest.model_validate(_save(payload, review, "k-v2")),
                        manager.id)
    assert getattr(error.value, "status_code", None) == 403
    assert archive.count_originals(store, "contract", contract_id) == 1


def test_a_failure_after_the_blocks_leaves_neither_document_nor_original(client, lease, monkeypatch):
    contract_id = lease["contract"].id
    payload, review = _preview(client, contract_id)
    original = archive.persist_version_bytes

    def fail_afterwards(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Datenträger voll")

    monkeypatch.setattr(archive, "persist_version_bytes", fail_afterwards)
    with pytest.raises(RuntimeError):
        _client_raising(client).post(_base(contract_id), json=_save(payload, review))
    assert archive.count_originals(store, "contract", contract_id) == 0
    assert not [d for d in store.list_documents() if d.file_url.startswith("/uploads/housing-confirmations/")]

    monkeypatch.setattr(archive, "persist_version_bytes", original)
    assert client.post(_base(contract_id), json=_save(payload, review)).status_code == 201


def _client_raising(client):
    return TestClient(app, headers=client.headers, raise_server_exceptions=True)


def test_a_file_on_disk_never_shadows_the_archived_original(client, lease):
    result = _publish(client, lease["contract"].id)
    shadow = get_uploads_dir() / "housing-confirmations" / f"{result['document_id']}.pdf"
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_bytes(b"%PDF-1.4 untergeschoben")
    try:
        served = client.get(result["file_url"]).content
        downloaded = client.get("/api/v1/files/download",
                                params={"key": f"housing-confirmations/{result['document_id']}.pdf"}).content
    finally:
        shadow.unlink()
    assert hashlib.sha256(served).hexdigest() == result["pdf_sha256"] == hashlib.sha256(downloaded).hexdigest()
    assert client.get("/uploads/housing-confirmations/not-a-uuid.pdf").status_code == 404


def test_title_edits_keep_the_evidence_and_the_document_stays(client, lease):
    result = _publish(client, lease["contract"].id)
    document_id = result["document_id"]

    assert client.patch(f"/api/v1/documents/{document_id}", json={"title": "WGB Muster"}).status_code == 200
    assert client.delete(f"/api/v1/documents/{document_id}").status_code == 409
    listed = client.get(_base(lease["contract"].id)).json()["items"]
    assert [item["document_id"] for item in listed] == [document_id]
    assert listed[0]["pdf_sha256"] == result["pdf_sha256"]


def test_damaged_evidence_is_reported_not_served(client, lease):
    result = _publish(client, lease["contract"].id)
    if SQL:
        with shared.db.get_bind().begin() as connection:
            from archive_helpers import drop_guards
            drop_guards(connection)
            connection.execute(text("UPDATE document_versions SET metadata_snapshot = :value WHERE id = :id"), {
                "id": result["version_id"],
                "value": __import__("json").dumps({**_snapshot(result["version_id"]), "document_date": "2020-01-01"}),
            })
            install_guards(connection)
        with shared.db.get_bind().connect() as connection:
            with pytest.raises(ArchiveIntegrityError):
                verify_document_versions(connection)
    else:
        row = archive.memory_archive(store).versions[result["version_id"]]
        row.metadata_snapshot["housing_confirmation"]["review"]["data"]["residents"] = ["Jemand anderes"]

    assert client.get(_base(lease["contract"].id)).status_code == 503
    assert client.get(result["file_url"]).status_code == 503


def _snapshot(version_id):
    from backend.db.document_version_models import DocumentVersionORM
    shared.db.expire_all()
    return shared.db.get(DocumentVersionORM, version_id).metadata_snapshot


@pytest.mark.skipif(not SQL, reason="offline check of a database")
def test_the_offline_check_accepts_published_confirmations(client, lease):
    _publish(client, lease["contract"].id)
    _publish(client, lease["contract"].id, key="wgb-2", move_in_date="2026-05-01")
    with shared.db.get_bind().connect() as connection:
        assert verify_document_versions(connection) == 2


def test_the_pdf_shows_what_was_reviewed():
    pdfplumber = pytest.importorskip("pdfplumber")
    from io import BytesIO

    from backend.services.housing_confirmation_render import render_pdf
    from backend.services.housing_confirmation_types import CertificateData

    data = CertificateData.model_validate(_data(owner_same_as_provider=False, owner_name="Élodie Beispiel",
                                                issuer_role="authorized_person", issuer_name="Hausverwaltung"))
    content = render_pdf({"data": data.model_dump(mode="json"), "source": {"contract": {"contract_number": "V-1"}}})
    assert render_pdf({"data": data.model_dump(mode="json"),
                       "source": {"contract": {"contract_number": "V-1"}}}) == content      # deterministic
    with pdfplumber.open(BytesIO(content)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        page_text = page.extract_text()
    assert "<br/>" not in page_text and "Tatsächliche Unterschrift" in page_text
    assert "03.02.2026" in page_text and "07.10.2026" in page_text and "Élodie Beispiel" in page_text
    for first_name in ("Mia", "Zoë", "Łukasz"):
        found = [word for word in words if word["text"] == first_name]
        assert len(found) == 1 and found[0]["x0"] > 95       # the wide name column, not the number column


def test_issue_and_move_in_dates_are_plain_dates():
    from backend.services.housing_confirmation_types import CertificateData

    data = CertificateData.model_validate(_data())
    assert data.move_in_date == date(2026, 2, 3)
    with pytest.raises(ValueError):
        CertificateData.model_validate(_data(owner_same_as_provider=False))     # owner name missing
    with pytest.raises(ValueError):
        CertificateData.model_validate(_data(residents=[]))
