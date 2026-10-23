"""Übergabeprotokoll: prefilled draft, protected photos, review, immutable original, readings into the billing.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (database triggers included);
PostgreSQL in test_handover_protocol_postgres.py.
"""

import hashlib
import os
import uuid
from datetime import date
from io import BytesIO

import pytest
import sqlalchemy as sa
from archive_helpers import purge_handover, purge_originals
from fastapi.testclient import TestClient
from PIL import Image

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import billing
from backend.services.data_snapshot import clear_business_data, export_snapshot, import_snapshot

SQL = os.environ.get("TEST_STORE_BACKEND", "memory") == "sql"
BASE = "/api/v1/handover-protocols"


def _reset_data():
    purge_handover(store)
    purge_originals(store)
    clear_business_data(store)


@pytest.fixture(autouse=True)
def _clean():
    _reset_data()
    auth.clear_users()
    yield
    _reset_data()
    auth.clear_users()


def _user(name, role="eigentuemer", **access):
    return auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role, **access)


def _client(user) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


@pytest.fixture
def owner():
    return _user("linda.reiser")


@pytest.fixture
def client(owner):
    return _client(owner)


def _estate(name="Bestand", number="V-1", rooms=2.0):
    portfolio = store.create_portfolio(PortfolioCreate(name=name, owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"{name} Bautzner Straße 61",
                                                property_type="residential", address_line="Bautzner Straße 61",
                                                postal_code="01099", city="Dresden"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential", rooms=rooms,
                                        area_sqm=60))
    tenant = store.create_tenant(TenantCreate(full_name=f"Mia Muster {number}"))
    contract = store.create_contract(ContractCreate(
        contract_number=number, property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        start_date=date(2024, 1, 1), end_date=date(2026, 6, 30), status="terminated"))
    meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water", serial_number=f"KW-{number}"))
    return {"portfolio": portfolio, "property": prop, "unit": unit, "tenant": tenant, "contract": contract,
            "meter": meter}


def _png(color=(200, 30, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (40, 30), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _new_id() -> str:
    return str(uuid.uuid4())


def _create(client, contract_id, kind="move_out", **extra):
    response = client.post(f"{BASE}/from-contract", json={"contract_id": contract_id, "protocol_type": kind, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def _content(detail, **changes):
    """The draft as the editor sends it."""
    protocol = detail["protocol"]
    body = {
        "base_revision": protocol["revision"],
        **{name: protocol[name] for name in ("protocol_date", "tenant_present", "landlord_present",
                                             "overall_condition", "notes", "tenant_signature", "landlord_signature")},
        "rooms": [{k: r[k] for k in ("id", "name", "condition", "notes")} for r in detail["rooms"]],
        "defects": [{k: d[k] for k in ("id", "room_id", "description", "responsible", "remedy", "due_date")}
                    for d in detail["defects"]],
        "keys": [{k: key[k] for k in ("id", "key_type", "label", "handed_over", "returned", "notes")}
                 for key in detail["keys"]],
        "meter_readings": [{k: m[k] for k in ("id", "meter_id", "meter_type", "meter_number", "reading_value",
                                              "unit", "notes")} for m in detail["meter_readings"]],
    }
    body.update(changes)
    return body


def _reading(meter_id, value):
    return {"id": _new_id(), "meter_id": meter_id, "meter_type": None, "meter_number": None, "reading_value": value,
            "unit": None, "notes": None}


def _save(client, detail, **changes):
    response = client.put(f"{BASE}/{detail['protocol']['id']}/content", json=_content(detail, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def _fill(client, detail, *, value=130.0, handed_over=3, returned=2):
    """Assess the rooms, record a defect in the kitchen, the flat keys and the meter."""
    rooms = [{"id": r["id"], "name": r["name"], "condition": "good", "notes": None} for r in detail["rooms"]]
    returned_value = returned if detail["protocol"]["protocol_type"] == "move_out" else None
    return _save(client, detail, rooms=rooms, defects=[{
        "id": _new_id(), "room_id": rooms[1]["id"], "description": "Bohrlöcher in der Küchenwand",
        "responsible": "tenant", "remedy": "Mieter verschließt die Löcher", "due_date": "2026-07-15"}],
        keys=[{"id": _new_id(), "key_type": "apartment_door", "label": "Wohnung", "handed_over": handed_over,
               "returned": returned_value, "notes": None}],
        meter_readings=[_reading(detail["meters"][0]["id"], value)])


def _finalize(client, protocol_id, key="handover-1"):
    preview = client.post(f"{BASE}/{protocol_id}/preview")
    assert preview.status_code == 200, preview.text
    preview = preview.json()
    assert preview["ready"], preview["problems"]
    response = client.post(f"{BASE}/{protocol_id}/finalize", json={
        "idempotency_key": key, "review_hash": preview["review_hash"], "confirmed_content": True,
        "confirmed_signatures": True})
    return preview, response


def _upload(client, protocol_id, content=None, name="kueche.png", **links):
    return client.post(f"{BASE}/{protocol_id}/photos", files={"file": (name, content or _png(), "image/png")},
                       data={key: value for key, value in links.items() if value is not None})


def _readings(meter_id):
    return sorted(((r.reading_date, r.value) for r in store.list_standalone_meter_readings() if r.meter_id == meter_id))


# ─── Drafts ──────────────────────────────────────────────────────────────────

def test_a_new_protocol_is_prefilled_from_the_unit_and_then_from_the_previous_protocol(client):
    estate = _estate()
    contract_id = estate["contract"].id
    source = client.get(f"{BASE}/source", params={"contract_id": contract_id, "protocol_type": "move_in"}).json()
    assert source["suggestion"]["protocol_date"] == "2024-01-01"
    assert source["suggestion"]["room_source"] == "unit_rooms"
    assert [r["name"] for r in source["suggestion"]["rooms"]] == ["Flur", "Küche", "Bad", "Zimmer 1", "Zimmer 2"]
    assert [m["serial_number"] for m in source["meters"]] == ["KW-V-1"]
    assert source["related"]["templates"] == []          # no tenant-change letter templates exist

    move_in = _create(client, contract_id, "move_in")
    assert move_in["created"] and move_in["protocol"]["protocol_date"] == "2024-01-01"
    assert move_in["protocol"]["tenant_signature"] == "Mia Muster V-1"
    assert move_in["protocol"]["landlord_signature"] == "Linda Reiser"
    assert _create(client, contract_id, "move_in")["protocol"]["id"] == move_in["protocol"]["id"]   # open draft reused

    rooms = [{"id": r["id"], "name": "Diele" if r["name"] == "Flur" else r["name"], "condition": "good",
              "notes": None} for r in move_in["rooms"]]
    saved = _save(client, move_in, rooms=rooms, keys=[{"id": _new_id(), "key_type": "apartment_door",
                                                        "label": "Wohnung", "handed_over": 3, "returned": None,
                                                        "notes": None}],
                  meter_readings=[_reading(estate["meter"].id, 100)])
    assert _finalize(client, saved["protocol"]["id"], "move-in")[1].status_code == 200

    move_out = _create(client, contract_id, "move_out")
    assert move_out["protocol"]["protocol_date"] == "2026-06-30"
    assert [r["name"] for r in move_out["rooms"]][:2] == ["Diele", "Küche"]
    assert [(k["key_type"], k["handed_over"], k["returned"]) for k in move_out["keys"]] == [
        ("apartment_door", 3, None)]
    assert move_out["meter_readings"] == []              # values are read at the handover, not copied
    assert move_out["meters"][0]["last_reading"] == {"reading_date": "2024-01-01", "value": 100.0}


def test_the_draft_is_saved_whole_against_its_revision(client):
    estate = _estate()
    detail = _create(client, estate["contract"].id)
    saved = _fill(client, detail)
    assert [d["description"] for d in saved["defects"]] == ["Bohrlöcher in der Küchenwand"]
    assert saved["defects"][0]["room_id"] == saved["rooms"][1]["id"]
    assert saved["meter_readings"][0]["meter_number"] == "KW-V-1" and saved["meter_readings"][0]["unit"] == "m³"

    stale = client.put(f"{BASE}/{detail['protocol']['id']}/content", json=_content(detail))
    assert stale.status_code == 409 and "inzwischen geändert" in stale.json()["error"]["message"]
    dangling = _content(saved, defects=[{"id": _new_id(), "room_id": _new_id(), "description": "x",
                                         "responsible": "open", "remedy": None, "due_date": None}])
    assert client.put(f"{BASE}/{detail['protocol']['id']}/content", json=dangling).status_code == 422
    foreign_meter = store.create_meter(MeterCreate(unit_id=_estate("Andere", "V-2")["unit"].id,
                                                   meter_type="cold_water"))
    wrong = _content(saved, meter_readings=[_reading(foreign_meter.id, 1)])
    assert client.put(f"{BASE}/{detail['protocol']['id']}/content", json=wrong).status_code == 409

    # removing a room drops it, keeps the others; the defect may stay as a general one
    rooms = _content(saved)["rooms"][2:]
    defect = {**_content(saved)["defects"][0], "room_id": None}
    trimmed = _save(client, saved, rooms=rooms, defects=[defect])
    assert [r["name"] for r in trimmed["rooms"]] == ["Bad", "Zimmer 1", "Zimmer 2"]
    assert trimmed["defects"][0]["room_id"] is None


def test_photos_are_protected_uploads_bound_to_the_draft(client):
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id))
    protocol_id, defect_id = detail["protocol"]["id"], detail["defects"][0]["id"]

    photo = _upload(client, protocol_id, defect_id=defect_id, caption="Bohrlöcher")
    assert photo.status_code == 201, photo.text
    photo = photo.json()
    assert photo["defect_id"] == defect_id and photo["sha256"] == hashlib.sha256(_png()).hexdigest()
    assert photo["file_url"].startswith(f"/uploads/handover-photos/{protocol_id}/")
    served = client.get(photo["file_url"])
    assert served.status_code == 200 and served.content == _png()
    assert TestClient(app).get(photo["file_url"]).status_code == 401      # never without a session

    assert _upload(client, protocol_id, b"not an image").status_code == 415
    assert _upload(client, protocol_id, name="plan.pdf").status_code == 415
    assert _upload(client, protocol_id, defect_id=_new_id()).status_code == 409    # unsaved row
    moved = client.patch(f"{BASE}/{protocol_id}/photos/{photo['id']}",
                         json={"defect_id": None, "room_id": detail["rooms"][0]["id"]})
    assert moved.status_code == 200 and moved.json()["room_id"] == detail["rooms"][0]["id"]
    assert client.delete(f"{BASE}/{protocol_id}/photos/{photo['id']}").status_code == 204
    assert client.get(photo["file_url"]).status_code == 404       # the file went with its last reference


def test_drafts_are_deleted_with_their_parts_and_files(client):
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id))
    photo = _upload(client, detail["protocol"]["id"]).json()
    assert client.delete(f"{BASE}/{detail['protocol']['id']}").status_code == 204
    assert client.get(f"{BASE}/{detail['protocol']['id']}/detail").status_code == 404
    assert store.list_meter_readings() == []
    assert client.get(photo["file_url"]).status_code == 404


# ─── Finalization ────────────────────────────────────────────────────────────

def test_finalizing_archives_the_reviewed_pdf_records_the_readings_and_locks_the_protocol(client):
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id))
    protocol_id = detail["protocol"]["id"]
    _upload(client, protocol_id, defect_id=detail["defects"][0]["id"], caption="Bohrlöcher")
    reviewed = client.post(f"{BASE}/{protocol_id}/preview-pdf")
    assert reviewed.status_code == 200 and reviewed.content.startswith(b"%PDF-")

    preview, response = _finalize(client, protocol_id)
    assert response.status_code == 200, response.text
    assert preview["pdf_sha256"] == hashlib.sha256(reviewed.content).hexdigest()
    final = response.json()
    assert final["state"]["finalized"] and not final["state"]["editable"]
    assert final["protocol"]["status"] == "finalized"
    original = final["original"]
    assert original["pdf_sha256"] == preview["pdf_sha256"] and original["content_matches"]

    # the original: as a download, under its document path, in the contract's documents
    download = client.get(f"{BASE}/{protocol_id}/document")
    assert download.status_code == 200 and download.content == reviewed.content
    assert client.get(original["file_url"]).content == reviewed.content
    documents = client.get("/api/v1/documents", params={"limit": 100}).json()
    documents = documents["items"] if isinstance(documents, dict) else documents
    generated = [d for d in documents if d["document_type"] == "handover_protocol"]
    assert [d["contract_id"] for d in generated] == [estate["contract"].id]

    # the meter reading is a real reading of the unit's meter for the protocol date
    assert _readings(estate["meter"].id) == [(date(2026, 6, 30), 130.0)]
    assert final["meter_readings"][0]["standalone_reading_id"]

    # nothing changes any more ...
    assert client.put(f"{BASE}/{protocol_id}/content", json=_content(final)).status_code == 409
    assert client.patch(f"{BASE}/{protocol_id}", json={"notes": "nachträglich"}).status_code == 409
    assert client.delete(f"{BASE}/{protocol_id}").status_code == 409
    assert _upload(client, protocol_id).status_code == 409
    assert client.delete(f"{BASE}/{protocol_id}/photos/{final['photos'][0]['id']}").status_code == 409
    assert client.post(f"{BASE}/{protocol_id}/meter-readings", json={
        "handover_id": protocol_id, "meter_type": "gas", "reading_value": 1}).status_code == 409
    assert client.delete(f"/api/v1/documents/{original['document_id']}").status_code == 409
    # ... except the follow-up of a defect, which the original does not contain
    resolved = client.patch(f"{BASE}/{protocol_id}/defects/{final['defects'][0]['id']}/follow-up",
                            json={"resolved_at": "2026-07-10", "resolution_note": "verspachtelt"})
    assert resolved.status_code == 200 and resolved.json()["defects"][0]["resolved_at"] == "2026-07-10"
    assert resolved.json()["original"]["content_matches"]

    # the same command again returns the same original; another one is refused
    again = _finalize_with(client, protocol_id, "handover-1", preview["review_hash"])
    assert again.status_code == 200 and again.json()["original"]["document_id"] == original["document_id"]
    assert _finalize_with(client, protocol_id, "handover-2", preview["review_hash"]).status_code == 409


def _finalize_with(client, protocol_id, key, review_hash):
    return client.post(f"{BASE}/{protocol_id}/finalize", json={
        "idempotency_key": key, "review_hash": review_hash, "confirmed_content": True, "confirmed_signatures": True})


@pytest.mark.skipif(not SQL, reason="database triggers exist on SQL stores only")
def test_the_database_refuses_changes_to_a_finalized_protocol(client):
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id))
    protocol_id = detail["protocol"]["id"]
    _upload(client, protocol_id)
    assert _finalize(client, protocol_id)[1].status_code == 200
    store.db.rollback()
    statements = [
        "UPDATE handover_protocols SET notes = 'x' WHERE id = :id",
        "DELETE FROM handover_protocols WHERE id = :id",
        "UPDATE handover_rooms SET name = 'x' WHERE protocol_id = :id",
        "DELETE FROM handover_keys WHERE protocol_id = :id",
        "UPDATE handover_photos SET caption = 'x' WHERE protocol_id = :id",
        "UPDATE meter_readings SET reading_value = 1 WHERE handover_id = :id",
        "UPDATE handover_defects SET description = 'x' WHERE protocol_id = :id",
        "DELETE FROM handover_defects WHERE protocol_id = :id",
    ]
    engine = store.db.get_bind()
    for statement in statements:
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                connection.execute(sa.text(statement), {"id": protocol_id})
    with engine.begin() as connection:     # the follow-up stays open
        connection.execute(sa.text("UPDATE handover_defects SET resolution_note = 'erledigt' WHERE protocol_id = :id"),
                           {"id": protocol_id})


def test_finalizing_needs_a_complete_protocol_and_exactly_the_reviewed_one(client):
    estate = _estate()
    detail = _create(client, estate["contract"].id)
    empty = _save(client, detail, rooms=[], tenant_signature=None)
    preview = client.post(f"{BASE}/{empty['protocol']['id']}/preview").json()
    codes = {problem["code"] for problem in preview["problems"] if problem["blocking"]}
    assert codes == {"NO_ROOMS", "TENANT_SIGNER_MISSING"} and not preview["ready"]
    refused = _finalize_with(client, empty["protocol"]["id"], "k", preview["review_hash"])
    assert refused.status_code == 409 and "nicht vollständig" in refused.json()["error"]["message"]

    rooms = [{"id": _new_id(), "name": name, "condition": None, "notes": None} for name in ("Bad", "Küche")]
    filled = _fill(client, _save(client, empty, tenant_signature="Mia Muster", rooms=rooms))
    preview = client.post(f"{BASE}/{filled['protocol']['id']}/preview").json()
    assert preview["ready"]
    _save(client, filled, notes="nach der Vorschau geändert")
    stale = _finalize_with(client, filled["protocol"]["id"], "k", preview["review_hash"])
    assert stale.status_code == 409 and "Vorschau" in stale.json()["error"]["message"]
    missing_return = _content(client.get(f"{BASE}/{filled['protocol']['id']}/detail").json())
    missing_return["keys"][0]["returned"] = None
    client.put(f"{BASE}/{filled['protocol']['id']}/content", json=missing_return)
    preview = client.post(f"{BASE}/{filled['protocol']['id']}/preview").json()
    assert "KEYS_RETURN_MISSING" in {p["code"] for p in preview["problems"] if p["blocking"]}
    assert client.patch(f"{BASE}/{filled['protocol']['id']}", json={"status": "finalized"}).status_code == 409


def test_an_existing_reading_of_the_day_is_attached_and_a_different_one_refused(client):
    estate = _estate()
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=estate["meter"].id,
                                                                       reading_date=date(2026, 6, 30), value=129))
    detail = _fill(client, _create(client, estate["contract"].id), value=130)
    preview = client.post(f"{BASE}/{detail['protocol']['id']}/preview").json()
    assert "METER_READING_CONFLICT" in {p["code"] for p in preview["problems"] if p["blocking"]}

    detail = _save(client, detail, meter_readings=[{**_content(detail)["meter_readings"][0], "reading_value": 129}])
    assert _finalize(client, detail["protocol"]["id"])[1].status_code == 200
    assert _readings(estate["meter"].id) == [(date(2026, 6, 30), 129.0)]     # attached, not doubled
    reading_id = next(r.id for r in store.list_standalone_meter_readings())
    assert client.delete(f"/api/v1/meters/readings/{reading_id}").status_code == 409
    assert client.delete(f"/api/v1/meters/{estate['meter'].id}").status_code == 409


# ─── Corrections ─────────────────────────────────────────────────────────────

def test_a_correction_is_a_new_original_and_takes_over_the_meter_reading(client):
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id), value=130)
    _upload(client, detail["protocol"]["id"], room_id=detail["rooms"][0]["id"])
    first = _finalize(client, detail["protocol"]["id"])[1].json()
    first_pdf = client.get(f"{BASE}/{first['protocol']['id']}/document").content

    started = client.post(f"{BASE}/{first['protocol']['id']}/corrections")
    assert started.status_code == 200 and started.json()["created"]
    draft = started.json()
    assert draft["protocol"]["correction_of_id"] == first["protocol"]["id"]
    assert [r["name"] for r in draft["rooms"]] == [r["name"] for r in first["rooms"]]
    assert draft["photos"][0]["file_url"] == first["photos"][0]["file_url"]       # the same file
    assert client.post(f"{BASE}/{first['protocol']['id']}/corrections").json()["protocol"]["id"] == \
        draft["protocol"]["id"]

    corrected = _save(client, draft, meter_readings=[{**_content(draft)["meter_readings"][0], "reading_value": 131.5}])
    final = _finalize(client, corrected["protocol"]["id"], "correction-1")[1]
    assert final.status_code == 200, final.text
    final = final.json()
    assert final["correction_of"]["id"] == first["protocol"]["id"]
    assert final["original"]["document_id"] != first["original"]["document_id"]
    # one reading, now with the corrected value; the first original stays byte for byte
    assert _readings(estate["meter"].id) == [(date(2026, 6, 30), 131.5)]
    assert client.get(f"{BASE}/{first['protocol']['id']}/document").content == first_pdf
    after = client.get(f"{BASE}/{first['protocol']['id']}/detail").json()
    assert after["state"]["superseded"] and after["original"]["content_matches"]
    assert client.post(f"{BASE}/{first['protocol']['id']}/corrections").status_code == 409
    photo = client.get(final["photos"][0]["file_url"])
    assert photo.status_code == 200


def test_a_correction_may_not_drop_a_meter_reading(client):
    estate = _estate()
    first = _finalize(client, _fill(client, _create(client, estate["contract"].id))["protocol"]["id"])[1].json()
    draft = client.post(f"{BASE}/{first['protocol']['id']}/corrections").json()
    draft = _save(client, draft, meter_readings=[])
    preview = client.post(f"{BASE}/{draft['protocol']['id']}/preview").json()
    assert "CORRECTION_DROPS_METER" in {p["code"] for p in preview["problems"] if p["blocking"]}


# ─── Billing ─────────────────────────────────────────────────────────────────

def test_handover_readings_split_the_consumption_at_the_tenant_change(client):
    """Without them the billing shares by days (test_utility_billing); with them it follows the meter."""
    pf = store.create_portfolio(PortfolioCreate(name="H"))
    prop = store.create_property(PropertyCreate(portfolio_id=pf.id, name="H", property_type="residential"))
    we06 = store.create_unit(UnitCreate(property_id=prop.id, label="WE 06", unit_type="residential", area_sqm=60,
                                        service_charge_advance=100))
    other = store.create_unit(UnitCreate(property_id=prop.id, label="WE 01", unit_type="residential", area_sqm=60,
                                         service_charge_advance=100))
    leases = {}
    for unit, number, start, end, status in ((we06, "L", date(2020, 1, 1), date(2025, 6, 30), "terminated"),
                                             (we06, "S", date(2025, 9, 1), None, "active"),
                                             (other, "O", date(2020, 1, 1), None, "active")):
        tenant = store.create_tenant(TenantCreate(full_name=f"Mieter {number}"))
        leases[number] = store.create_contract(ContractCreate(
            contract_number=number, property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id, start_date=start,
            end_date=end, status=status))
    meters = {}
    for unit, values in ((other, [(date(2024, 12, 31), 0), (date(2025, 12, 31), 50)]),
                         (we06, [(date(2024, 12, 31), 100), (date(2025, 12, 31), 150)])):
        meters[unit.id] = store.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water"))
        for day, value in values:
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
                meter_id=meters[unit.id].id, reading_date=day, value=value))
    period = store.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="BK",
                                                             start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Wasser",
                                                          key_type="consumption"))
    store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Wasser", amount=1000,
                                          allocation_key_id=key.id))
    assert "MISSING_INTERMEDIATE_READING" in {w.code for w in billing.get_billing_period_preflight(period.id).warnings}

    for number, kind, value in (("L", "move_out", 130), ("S", "move_in", 131)):
        detail = _create(client, leases[number].id, kind)
        rooms = [{"id": _new_id(), "name": "Wohnküche", "condition": "good", "notes": None}]
        detail = _save(client, detail, rooms=rooms, landlord_signature="Hausverwaltung H",
                       meter_readings=[_reading(meters[we06.id].id, value)])
        assert _finalize(client, detail["protocol"]["id"], f"{number}-{kind}")[1].status_code == 200

    assert "MISSING_INTERMEDIATE_READING" not in {
        w.code for w in billing.get_billing_period_preflight(period.id).warnings}
    rows = {(s.party, s.usage_start): s.total_cost
            for s in billing.generate_utility_statements(period.id) if s.unit_id == we06.id}
    # WE 06: 30 m³ until the move-out, 1 m³ vacant, 19 m³ after the move-in — of 100 m³ in total
    assert rows == {("tenant", date(2025, 1, 1)): 300.0, ("vacancy", date(2025, 7, 1)): 10.0,
                    ("tenant", date(2025, 9, 1)): 190.0}


# ─── Access ──────────────────────────────────────────────────────────────────

def test_a_restricted_account_sees_and_changes_only_protocols_of_its_portfolios(client):
    north, south = _estate("Nord", "N-1"), _estate("Süd", "S-1")
    drafts = {}
    for side, estate in (("north", north), ("south", south)):
        detail = _fill(client, _create(client, estate["contract"].id))
        photo = _upload(client, detail["protocol"]["id"]).json()
        drafts[side] = (detail["protocol"]["id"], photo)
    south_final = _finalize(client, drafts["south"][0])[1].json()

    staff = _client(_user("staff", "verwalter", portfolio_access="selected", portfolio_ids=[north["portfolio"].id]))
    listed = {p["id"] for p in staff.get(BASE, params={"limit": 1000}).json()}
    assert listed == {drafts["north"][0]}
    south_id, south_photo = drafts["south"]
    assert staff.get(f"{BASE}/{south_id}/detail").status_code == 404
    assert staff.get(f"{BASE}/{south_id}").status_code == 404
    assert staff.get(south_photo["file_url"]).status_code == 404
    assert staff.get(south_final["original"]["file_url"]).status_code == 404
    assert staff.get(f"{BASE}/{south_id}/document").status_code == 404
    assert staff.get("/api/v1/files/download", params={"key": south_photo["file_url"][len("/uploads/"):]}
                     ).status_code == 404
    assert staff.get(f"{BASE}/source", params={"contract_id": south["contract"].id, "protocol_type": "move_out"}
                     ).status_code == 404
    assert staff.post(f"{BASE}/from-contract", json={"contract_id": south["contract"].id,
                                                     "protocol_type": "move_in"}).status_code == 404
    assert staff.put(f"{BASE}/{south_id}/content", json=_content(south_final)).status_code in (404, 409)
    assert _upload(staff, south_id).status_code == 404
    assert staff.post(f"{BASE}/{south_id}/corrections").status_code == 404

    # its own portfolio: read, add a photo, finalize
    north_id, north_photo = drafts["north"]
    assert staff.get(north_photo["file_url"]).status_code == 200
    own = _upload(staff, north_id, _png((10, 200, 10)))
    assert own.status_code == 201, own.text
    assert staff.get(own.json()["file_url"]).status_code == 200
    final = _finalize(staff, north_id, "staff-1")[1]
    assert final.status_code == 200, final.text
    assert staff.get(final.json()["original"]["file_url"]).status_code == 200


def test_roles_decide_who_drafts_and_finalizes(client):
    estate = _estate()
    payload = {"contract_id": estate["contract"].id, "protocol_type": "move_out"}
    for role in ("buchhaltung", "readonly"):
        assert _client(_user(f"user.{role}", role)).post(f"{BASE}/from-contract", json=payload).status_code == 403
    technician = _client(_user("tech", "techniker"))
    detail = technician.post(f"{BASE}/from-contract", json=payload)
    assert detail.status_code == 200
    detail = _fill(technician, detail.json())
    assert _finalize(technician, detail["protocol"]["id"])[1].status_code == 200
    readonly = _client(_user("reader", "readonly"))
    assert readonly.get(f"{BASE}/{detail['protocol']['id']}/detail").status_code == 200


# ─── Snapshot, data access, PDF ──────────────────────────────────────────────

def test_snapshots_carry_the_protocol_its_parts_and_its_original(client):
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id))
    _upload(client, detail["protocol"]["id"], defect_id=detail["defects"][0]["id"])
    final = _finalize(client, detail["protocol"]["id"])[1].json()
    data = export_snapshot(store)
    assert {len(data[name]) for name in ("handover_rooms", "handover_defects", "handover_keys",
                                         "handover_photos")} >= {1}
    assert data["meter_readings"][0]["standalone_reading_id"]
    assert [o["metadata_snapshot"]["document_type"] for o in data["document_originals"]] == ["handover_protocol"]

    _reset_data()
    import_snapshot(store, data, replace=True)
    restored = client.get(f"{BASE}/{final['protocol']['id']}/detail").json()
    assert restored["state"]["finalized"] and restored["original"]["content_matches"]
    assert [r["name"] for r in restored["rooms"]] == [r["name"] for r in final["rooms"]]
    assert hashlib.sha256(client.get(f"{BASE}/{final['protocol']['id']}/document").content).hexdigest() == \
        final["original"]["pdf_sha256"]


def test_the_data_access_export_lists_the_protocol_parts(client):
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id))
    _upload(client, detail["protocol"]["id"])
    export = client.get(f"/api/v1/admin/dsgvo/tenant/{estate['tenant'].id}/export").json()
    counts = {name: len(export[name]) for name in ("handover_protocols", "handover_rooms", "handover_defects",
                                                   "handover_keys", "handover_meter_readings", "handover_photos")}
    assert counts == {"handover_protocols": 1, "handover_rooms": 5, "handover_defects": 1, "handover_keys": 1,
                      "handover_meter_readings": 1, "handover_photos": 1}


def test_the_pdf_names_rooms_defects_keys_meters_and_signers(client):
    pdfplumber = pytest.importorskip("pdfplumber")
    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id), handed_over=3, returned=2)
    _upload(client, detail["protocol"]["id"], defect_id=detail["defects"][0]["id"], caption="Bohrlöcher")
    content = client.post(f"{BASE}/{detail['protocol']['id']}/preview-pdf").content
    with pdfplumber.open(BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        images = sum(len(page.images) for page in pdf.pages)
    for expected in ("ÜBERGABEPROTOKOLL – AUSZUG", "Zimmer 2", "Bohrlöcher in der Küchenwand", "Mieter verschließt",
                     "Wohnungstür", "KW-V-1", "130", "Mia Muster V-1", "Linda Reiser", "Foto 1"):
        assert expected in text, expected
    assert images == 1
    assert content == client.post(f"{BASE}/{detail['protocol']['id']}/preview-pdf").content    # deterministic


@pytest.mark.skipif(not SQL, reason="the backup check reads a SQL database")
def test_the_backup_check_proves_handover_originals(client):
    from backend.services.document_version_validation import verify_document_versions

    estate = _estate()
    detail = _fill(client, _create(client, estate["contract"].id))
    assert _finalize(client, detail["protocol"]["id"])[1].status_code == 200
    store.db.rollback()
    with store.db.get_bind().connect() as connection:
        assert verify_document_versions(connection) == 1
