"""Manual worksheet provenance and negative manufacturer claims, Memory/SQLite."""

import csv
import io
import json
from datetime import date
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.models import BookingPatch, PortfolioCreate, PropertyCreate, PropertyPatch
from backend.services import annual_tax_projection
from backend.services import annual_tax_storage as storage
from backend.services.annual_tax_export import prepare_download
from backend.services.wiso_preparation import evidence_catalog, saved_preparation
from backend.tax_models import AnnualTaxPreflightCreate, AnnualTaxProfileCreate
from backend.tests.test_annual_tax_access import headers
from backend.tests.test_annual_tax_access import tax_http as tax_http  # noqa: F401
from backend.tests.test_annual_tax_projection import booking, profile_command, save_command
from backend.tests.test_annual_tax_projection import tax_store as tax_store  # noqa: F401


@pytest.fixture(autouse=True)
def completed_year(monkeypatch):
    monkeypatch.setattr(annual_tax_projection, "local_today", lambda: date(2027, 1, 2))


def preparation_configuration(fixture):
    _, _, _, properties, *_ = fixture
    return {"objects": [{"property_id": prop.id, "object_number": i + 1,
                "target_object_label": f"Reviewed target {i + 1}"} for i, prop in enumerate(properties)],
        "lines": [{"treatment": "income", "form_line": "User form income", "target_label": "Manually checked rent label",
                "review_reason": "Explicit manual screen review; no manufacturer field number"},
            {"treatment": "expense", "form_line": "User form costs", "target_label": "Manually checked cost label",
                "review_reason": "Paid costs reviewed for manual entry"}]}


def wiso_profile(fixture, **changes):
    return profile_command(fixture, **({"tax_year": 2026, "wiso_preparation": preparation_configuration(fixture)} | changes))


def wiso_cash(fixture):
    first = booking(fixture, 100.01, day=date(2026, 1, 1))
    booking(fixture, -0.01, day=date(2026, 1, 2))
    booking(fixture, -30.10, category=1, day=date(2026, 2, 1))
    booking(fixture, 10.01, category=1, day=date(2026, 3, 1))
    return first


def test_complete_manual_preparation_preserves_original_cents_profile_and_download(tax_store):
    store, _, _, properties, *_ = tax_store
    first = wiso_cash(tax_store)
    booking(tax_store, 5.67, prop=1, day=date(2026, 4, 1))
    profile = storage.create_profile(store, wiso_profile(tax_store), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=profile["id"], as_of=date(2026, 12, 31))
    checked = storage.preflight(store, command)
    report = checked["wiso_preparation"]
    assert report["manual_transfer_ready"] and not report["vendor_file_ready"] and not report["target_import_verified"]
    assert report["mapped_totals"] == {"income_cents": "10567", "expense_cents": "2009"}
    assert report["unmapped_totals"] == {"income_cents": "0", "expense_cents": "0"}
    assert [(row["object_number"], row["amount_eur"], row["source_parts"]) for row in report["rows"]] == [(1, "20,09", 2), (1, "100,00", 2), (2, "5,67", 1)]
    saved = storage.create_projection(store, save_command(command, checked), "actor")
    assert storage.create_projection(store, save_command(command, checked), "actor")["id"] == saved["id"]
    assert saved_preparation(store, saved["id"]) == report
    first_download = prepare_download(store, saved["id"])
    try:
        original = first_download.path.read_bytes()
        with ZipFile(io.BytesIO(original)) as archive:
            assert not any(name.endswith(".xml") for name in archive.namelist())
            assert json.loads(archive.read("reviewed-profile.json")) == profile
            assert json.loads(archive.read("wiso-manual-preparation.json")) == report
            assert "keine importierbare WISO-Datei" in archive.read("README-manual-transfer.txt").decode()
            rows = list(csv.DictReader(io.StringIO(archive.read("manual-transfer-worksheet.csv").decode("utf-8-sig")), delimiter=";"))
            assert [row["amount_cents"] for row in rows] == ["2009", "10000", "567"]
            assert all(row["profile_version_id"] == profile["id"] for row in rows)
            assert len(archive.read("sources.jsonl").splitlines()) == 5
    finally:
        first_download.close()
    store._patch_entity("booking", first.id, BookingPatch(amount=999))
    store._patch_entity("property", properties[0].id, PropertyPatch(name="Later changed source name"))
    config = preparation_configuration(tax_store)
    config["objects"][0]["target_object_label"] = "Successor label"
    storage.create_profile(store, wiso_profile(tax_store, previous_version_id=profile["id"], idempotency_key="successor",
        wiso_preparation=config), "actor")
    second = prepare_download(store, saved["id"])
    try:
        assert second.path.read_bytes() == original
    finally:
        second.close()
    assert saved_preparation(store, saved["id"]) == report


def test_missing_mapping_zero_and_negative_groups_remain_explicit(tax_store):
    store, *_ = tax_store
    booking(tax_store, 0.01, day=date(2026, 1, 1))
    booking(tax_store, -0.01, day=date(2026, 1, 2))
    booking(tax_store, -0.01, prop=1, day=date(2026, 1, 3))
    config = preparation_configuration(tax_store)
    config["objects"] = config["objects"][:1]
    config["lines"] = []
    profile = storage.create_profile(store, wiso_profile(tax_store, wiso_preparation=config), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=profile["id"], as_of=date(2026, 6, 30))
    checked = storage.preflight(store, command)
    report = checked["wiso_preparation"]
    assert checked["ready"] and not report["manual_transfer_ready"] and report["reconciled"]
    assert report["mapped_totals"]["income_cents"] == "0" and report["unmapped_totals"]["income_cents"] == "-1"
    assert [row["amount_eur"] for row in report["rows"]] == ["0,00", "-0,01"]
    assert len([issue for issue in report["issues"] if issue["code"] == "mapping_incomplete"]) == 2
    assert any(issue["code"] == "partial_year" for issue in report["issues"])
    saved = storage.create_projection(store, save_command(command, checked), "actor")
    assert saved_preparation(store, saved["id"]) == report
    compiled = prepare_download(store, saved["id"])
    try:
        with ZipFile(compiled.path) as archive:
            rows = list(csv.DictReader(io.StringIO(archive.read("manual-transfer-worksheet.csv").decode("utf-8-sig")), delimiter=";"))
            assert [(row["amount_cents"], row["amount_eur"], row["mapping_complete"]) for row in rows] == [("0", "0,00", "False"), ("-1", "-0,01", "False")]
    finally:
        compiled.close()


def test_profile_cas_idempotency_and_unknown_vendor_fields_are_rejected(tax_store):
    store, *_ = tax_store
    profile = storage.create_profile(store, wiso_profile(tax_store), "actor")
    assert storage.create_profile(store, wiso_profile(tax_store), "actor") == profile
    config = preparation_configuration(tax_store)
    config["lines"][0]["target_label"] = "A different destination"
    with pytest.raises(HTTPException) as conflict:
        storage.create_profile(store, wiso_profile(tax_store, wiso_preparation=config), "actor")
    assert conflict.value.status_code == 409
    storage.create_profile(store, wiso_profile(tax_store, idempotency_key="next", previous_version_id=profile["id"]), "actor")
    with pytest.raises(HTTPException) as conflict:
        storage.create_profile(store, wiso_profile(tax_store, idempotency_key="fork", previous_version_id=profile["id"]), "actor")
    assert conflict.value.status_code == 409
    for changes in ({"tax_year": 2025}, {"wiso_preparation": {"field_nr": "0700201"}},
                    {"wiso_preparation": {"target_product": "WISO Hausverwalter"}},
                    {"wiso_preparation": {"objects": preparation_configuration(tax_store)["objects"] * 2}},
                    {"wiso_preparation": {"lines": preparation_configuration(tax_store)["lines"] * 2}}):
        with pytest.raises(ValidationError):
            wiso_profile(tax_store, **changes)


def test_retained_preparation_refuses_corrupt_group_even_with_rehashed_manifest(tax_store):
    store, *_ = tax_store
    wiso_cash(tax_store)
    profile = storage.create_profile(store, wiso_profile(tax_store), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=profile["id"], as_of=date(2026, 12, 31))
    checked = storage.preflight(store, command)
    saved = storage.create_projection(store, save_command(command, checked), "actor")
    row = storage.projection_row(store, saved["id"])
    manifest = json.loads(row.manifest_json)
    manifest["wiso_preparation"]["rows"][0]["target_label"] = "Unreviewed substituted target"
    row.manifest_json = annual_tax_projection.canonical(manifest).decode()
    row.manifest_sha256 = annual_tax_projection.fingerprint(manifest)
    with pytest.raises(HTTPException) as corrupt:
        saved_preparation(store, saved["id"])
    assert corrupt.value.status_code == 503
    with pytest.raises(HTTPException):
        prepare_download(store, saved["id"])


def test_evidence_catalog_keeps_observation_and_field_semantics_separate():
    evidence = evidence_catalog()
    assert evidence["target_tax_year"] == 2026
    assert not evidence["vendor_serializer_available"] and not evidence["target_import_verified"]
    assert evidence["samples"][0]["object_field_counts"] == [34, 17]
    assert evidence["samples"][1]["object_field_counts"] == [36, 23]
    assert evidence["samples"][2]["isolated_field_meaning_verified"] is False
    assert {field["wert"] for field in evidence["samples"][2]["observed_fields"]} == {"2.5", "1234,56"}
    assert len(evidence["missing_evidence"]) == 3


def test_neutral_profile_remains_usable_and_has_no_preparation(tax_store):
    store, *_ = tax_store
    booking(tax_store, 1.01)
    profile = storage.create_profile(store, profile_command(tax_store), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=profile["id"], as_of=date(2024, 12, 31))
    checked = storage.preflight(store, command)
    saved = storage.create_projection(store, save_command(command, checked), "actor")
    assert "wiso_preparation" not in checked
    legacy_spec = profile_command(tax_store).model_dump(mode="json", exclude={"idempotency_key", "previous_version_id", "wiso_preparation"})
    assert profile["spec"] == legacy_spec
    assert profile["sha256"] == annual_tax_projection.fingerprint(legacy_spec)
    assert storage.create_profile(store, AnnualTaxProfileCreate(**profile_command(tax_store).model_dump(exclude={"wiso_preparation"})), "actor") == profile
    neutral = prepare_download(store, saved["id"])
    try:
        with ZipFile(neutral.path) as archive:
            assert set(archive.namelist()) == {"manifest.json", "sources.jsonl", "tax-lines.csv", "cash-evidence.csv"}
    finally:
        neutral.close()
    with pytest.raises(HTTPException) as missing:
        saved_preparation(store, saved["id"])
    assert missing.value.status_code == 422
    # Existing stored specs lacking the new optional key remain readable.
    legacy = profile_command(tax_store).model_dump(exclude={"wiso_preparation"})
    assert AnnualTaxProfileCreate(**legacy).wiso_preparation is None


def test_http_retained_preparation_and_archive_require_current_access(tax_store, tax_http):
    from backend import auth

    store, _, portfolio, *_ = tax_store
    wiso_cash(tax_store)
    profile = storage.create_profile(store, wiso_profile(tax_store), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=profile["id"], as_of=date(2026, 12, 31))
    saved = storage.create_projection(store, save_command(command, storage.preflight(store, command)), "actor")
    user, token = headers("readonly", portfolio.id)
    base = "/api/v1/reports/annual-tax"
    suffix = f"/projections/{saved['id']}/wiso-preparation"
    assert tax_http.get(base + suffix).status_code == 401
    assert tax_http.get(base + "/wiso/evidence").status_code == 401
    assert tax_http.get(base + "/wiso/evidence", headers=token).json()["vendor_serializer_available"] is False
    result = tax_http.get(base + suffix, headers=token)
    assert result.status_code == 200 and result.json()["mapped_totals"]["income_cents"] == "10000"
    assert tax_http.post(base + "/profiles", headers=token, json=wiso_profile(tax_store).model_dump(mode="json")).status_code == 403
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
    for endpoint in (suffix, f"/projections/{saved['id']}/download"):
        denied = tax_http.get(base + endpoint, headers=token)
        assert denied.status_code == 404
        assert "content-disposition" not in denied.headers


def test_even_unused_profile_object_labels_cannot_disclose_a_moved_object(tax_store, tax_http):
    store, _, portfolio, properties, *_ = tax_store
    wiso_cash(tax_store)
    profile = storage.create_profile(store, wiso_profile(tax_store), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=profile["id"], as_of=date(2026, 12, 31))
    saved = storage.create_projection(store, save_command(command, storage.preflight(store, command)), "actor")
    _, token = headers("buchhaltung", portfolio.id)
    foreign = store.create_portfolio(PortfolioCreate(name="Foreign private portfolio"))
    foreign_property = store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Foreign object", property_type="residential"))
    config = preparation_configuration(tax_store)
    config["objects"][0]["property_id"] = foreign_property.id
    denied = tax_http.post("/api/v1/reports/annual-tax/profiles", headers=token,
        json=wiso_profile(tax_store, idempotency_key="foreign", wiso_preparation=config).model_dump(mode="json"))
    assert denied.status_code == 404
    # No booking references this second configured object. Its label remains private.
    store._patch_entity("property", properties[1].id, PropertyPatch(portfolio_id=foreign.id))
    for endpoint in (f"/profiles/{profile['id']}", f"/projections/{saved['id']}/wiso-preparation",
                     f"/projections/{saved['id']}/download", f"/profiles?portfolio_id={portfolio.id}",
                     f"/projections/{saved['id']}", f"/projections?portfolio_id={portfolio.id}"):
        result = tax_http.get("/api/v1/reports/annual-tax" + endpoint, headers=token)
        assert result.status_code == 404, result.text
