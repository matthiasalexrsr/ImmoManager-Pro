"""Whole-file JSON decoding and repeatable upload-budget failures."""

import asyncio
import json
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from backend.models import ContactCreate
from backend.routers import data_exchange
from backend.tests.test_restore_transfer import active_store as active_store
from backend.tests.test_restore_transfer import canonical_snapshot
from backend.tests.test_restore_transfer import http_client as http_client


@pytest.mark.parametrize("raw", [
    b'{"contacts": [{"contact_type": "supplier", "company_name": "First"}], "contacts": []}',
    b'{"contacts": [{"contact_type": "supplier", "company_name": "First", "company_name": "Last"}]}',
    b'{"contacts": [{"contact_type": "supplier", "notes": NaN}]}',
    b'{"contacts": [{"contact_type": "supplier", "notes": Infinity}]}',
    b'{"contacts": [{"contact_type": "supplier", "notes": -Infinity}]}',
    b'[]',
    b'{"contacts": [',
    b'{"contacts": [{"contact_type": "supplier", "company_name": "\xff"}]}',
    b'{"contacts": [{"contact_type": "supplier", "future_field": "must not disappear"}]}',
])
def test_invalid_file_rejected_without_importing_records(active_store, http_client, raw):
    client, headers, _, _ = http_client
    active_store.create_contact(ContactCreate(contact_type="supplier", company_name="Existing"))
    before = canonical_snapshot(active_store)

    response = client.post("/api/v1/data/import", headers=headers,
                           files={"file": ("invalid.json", raw, "application/json")})

    assert response.status_code == 400, response.text
    assert canonical_snapshot(active_store) == before


def test_byte_budget_rejection_is_retryable_and_exact_boundary_preserves_all_records(
    active_store, http_client, monkeypatch,
):
    client, headers, _, _ = http_client
    existing = active_store.create_contact(ContactCreate(contact_type="supplier", company_name="Existing"))
    names = ["Anfang", "Mitte", "Spätes vollständig erhaltenes ÄÖÜ-Ende"]
    raw = json.dumps({"contacts": [{"contact_type": "supplier", "company_name": name} for name in names]},
                     ensure_ascii=False).encode("utf-8")
    assert len(raw) > len(raw.decode("utf-8"))
    before = canonical_snapshot(active_store)
    monkeypatch.setattr(data_exchange.settings, "max_upload_size_bytes", len(raw) - 1)

    rejected = client.post("/api/v1/data/import", headers=headers,
                           files={"file": ("complete.json", raw, "application/json")})
    assert rejected.status_code == 413, rejected.text
    message = rejected.json()["error"]["message"]
    assert str(len(raw) - 1) in message
    assert "erneut" in message
    assert canonical_snapshot(active_store) == before

    monkeypatch.setattr(data_exchange.settings, "max_upload_size_bytes", len(raw))
    accepted = client.post("/api/v1/data/import", headers=headers,
                           files={"file": ("complete.json", raw, "application/json")})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["imported"]["contacts"] == len(names)
    contacts = active_store.list_contacts()
    assert {item.company_name for item in contacts} == {"Existing", *names}
    assert any(item.id == existing.id for item in contacts)


def test_oversized_source_is_not_read_to_eof(monkeypatch):
    maximum = 128
    monkeypatch.setattr(data_exchange.settings, "max_upload_size_bytes", maximum)
    source = BytesIO(b"x" * (maximum * 100))
    upload = UploadFile(file=source, filename="large.json")

    with pytest.raises(HTTPException) as failure:
        asyncio.run(data_exchange.import_data(upload))

    assert failure.value.status_code == 413
    assert source.tell() == maximum + 1


@pytest.mark.parametrize("maximum", [0, -2])
def test_invalid_budget_fails_before_reading_and_identifies_configuration(monkeypatch, maximum):
    monkeypatch.setattr(data_exchange.settings, "max_upload_size_bytes", maximum)
    source = BytesIO(b'{"contacts": []}')
    upload = UploadFile(file=source, filename="complete.json")

    with pytest.raises(HTTPException) as failure:
        asyncio.run(data_exchange.import_data(upload))

    assert failure.value.status_code == 503
    assert "MAX_UPLOAD_SIZE_BYTES" in failure.value.detail
    assert source.tell() == 0
