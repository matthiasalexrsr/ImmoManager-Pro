"""Isolation across every portal transport, including households in one building."""
import io
import json
import zipfile
from datetime import date, timedelta
from uuid import uuid4

import pytest
import test_data_transfer as transfer_fixtures
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete

from backend import auth
from backend.app import app
from backend.config import settings
from backend.db import external_portal_models as pm
from backend.db.orm_models import Base
from backend.dependencies import store
from backend.external_portal_models import ChangeAccess, InviteParty, PublishDocument, RecoverAccess
from backend.models import (
    ContactCreate,
    ContractCreate,
    DocumentCreate,
    MaintenanceCaseCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.models_ownership import OwnershipShareCreate
from backend.services import document_versions as archive
from backend.services import ownership
from backend.services.external_portal import admin, common
from backend.services.integrations import connection_storage as db

ORIGIN = "https://portal.example.test"
HEADERS = {"Origin": ORIGIN, "X-Portal-Client": "web-v1"}


def purge():
    for table in reversed(Base.metadata.sorted_tables):
        if not table.name.startswith("external_portal_"):
            continue
        if hasattr(store, "db"):
            store.db.execute(delete(table))
        else:
            store.__dict__.get("_integration_connections", {}).pop(table.name, None)
    if hasattr(store, "db"):
        store.db.commit()
    transfer_fixtures.purge()


@pytest.fixture
def portal(monkeypatch):
    purge()
    monkeypatch.setattr(settings, "portal_enabled", True)
    monkeypatch.setattr(settings, "portal_public_url", ORIGIN)
    monkeypatch.setattr(settings, "portal_local_test_mode", False)
    owner = auth.register_user("office", "office@example.test", "Office", "Secret123", "eigentuemer")
    from backend.models import PortfolioCreate
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Gemeinsames Haus", property_type="residential"))
    households = []
    for number in (1, 2):
        tenant = store.create_tenant(TenantCreate(full_name=f"Haushalt {number}", email=f"tenant{number}@example.test"))
        place = store.create_unit(UnitCreate(property_id=prop.id, label=f"WE {number}", unit_type="residential"))
        contract = store.create_contract(ContractCreate(property_id=prop.id, unit_id=place.id, tenant_id=tenant.id,
            contract_number=f"MV{number}", start_date=date(2025, 1, 1)))
        invited = admin.invite(store, owner.id, InviteParty(kind="tenant", party_id=tenant.id, relation_id=contract.id,
            email=str(tenant.email), verification="Identität und persönliche E-Mail gegengeprüft.", idempotency_key=uuid4().hex))
        client = TestClient(app, base_url=ORIGIN, headers=HEADERS)
        response = client.post("/api/v1/portal/accept", json={"token": invited["invitation_url"].split("#")[1], "password": "PortalPassword123"})
        assert response.status_code == 200, response.text
        grant_id = client.get("/api/v1/portal/me").json()["grants"][0]["id"]
        households.append(dict(tenant=tenant, place=place, contract=contract, invitation=invited, client=client, grant_id=grant_id))
    office = TestClient(app, base_url=ORIGIN, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    yield dict(owner=owner, portfolio=portfolio, prop=prop, households=households, office=office)
    purge()


def document(portal, household=None):
    fields = {"property_id": portal["prop"].id}
    if household:
        fields.update(unit_id=household["place"].id, contract_id=household["contract"].id, tenant_id=household["tenant"].id)
    doc = store.create_document(DocumentCreate(title="Private Originalfassung", file_url="/uploads/portal-fixtures/" + uuid4().hex + ".pdf", **fields))
    with archive.work(store, portal["owner"].id, write_areas=("/documents",)) as unit:
        _, binding = archive.bind_document(unit, doc.id)
        version = archive.publish_generated_original(unit, doc, binding, b"%PDF-1.7\nprivate original\n%%EOF", "a" * 64, version_id=str(uuid4()))
        return doc, version


def publish(portal, household, version):
    grants = admin.listing(store, portal["owner"].id)["items"]
    access = next(row for row in grants if row["id"] == household["grant_id"])
    return admin.publish(store, portal["owner"].id, access["id"], PublishDocument(grant_revision=access["revision"],
        version_id=version.id, title="Nur für diesen Haushalt", reason="Eigene Vertragsunterlage ausdrücklich freigegeben.", idempotency_key=uuid4().hex))


def damage(household, image=False):
    client = household["client"]
    access = client.get("/api/v1/portal/me").json()["grants"][0]
    command = {"grant_id": access["id"], "expected_revision": access["revision"], "idempotency_key": uuid4().hex,
        "title": "Wasser am Fenster", "body": "Bei Regen tritt Wasser am Fenster ein."}
    files = []
    if image:
        out = io.BytesIO()
        Image.new("RGB", (4, 4), "blue").save(out, "PNG")
        files = [("files", ("schaden.png", out.getvalue(), "image/png"))]
    result = client.post("/api/v1/portal/me/cases", data={"command": json.dumps(command)}, files=files)
    assert result.status_code == 201, result.text
    return result.json(), command, files


def test_verified_password_recovery_revokes_sessions_and_all_other_relations(portal):
    first, second = portal['households']
    place = store.create_unit(UnitCreate(property_id=portal['prop'].id, label='Zusätzliche Wohnung', unit_type='residential'))
    additional = store.create_contract(ContractCreate(property_id=portal['prop'].id, unit_id=place.id,
        tenant_id=first['tenant'].id, contract_number='MV-recovery', start_date=date(2025, 1, 1)))
    invite = admin.invite(store, portal['owner'].id, InviteParty(kind='tenant', party_id=first['tenant'].id,
        relation_id=additional.id, email=first['tenant'].email, verification='Zusätzliches Mietverhältnis persönlich geprüft.', idempotency_key=uuid4().hex))
    assert first['client'].post('/api/v1/portal/accept', json={'token': invite['invitation_url'].split('#')[1],
        'password': 'PortalPassword123'}).status_code == 200
    assert len(first['client'].get('/api/v1/portal/me').json()['grants']) == 2
    current = next(row for row in admin.listing(store, portal['owner'].id)['items'] if row['id'] == first['grant_id'])
    command = RecoverAccess(expected_revision=current['identity_revision'], grant_revision=current['revision'],
        verification='Persönlichen Ausweis und bekannte Rückrufnummer unabhängig geprüft.', idempotency_key=uuid4().hex)
    result = admin.recover_access(store, portal['owner'].id, first['grant_id'], command)
    token = result['invitation_url'].split('#')[1]
    assert first['client'].get('/api/v1/portal/me').status_code == 401
    assert second['client'].get('/api/v1/portal/me').status_code == 200
    assert first['client'].post('/api/v1/portal/login', json={'email': first['tenant'].email,
        'password': 'PortalPassword123'}).status_code == 401
    with common.raw_work(store) as unit:
        assert all(token not in str(db.values(row)) for model in (pm.PortalInvitationORM, pm.PortalCommandORM, pm.PortalEventORM)
                   for row in common.rows(unit, model))
    response = first['client'].post('/api/v1/portal/accept', json={'token': token, 'password': 'NewPortalPassword456'})
    assert response.status_code == 200, response.text
    assert [row['id'] for row in first['client'].get('/api/v1/portal/me').json()['grants']] == [first['grant_id']]
    replayed = admin.recover_access(store, portal['owner'].id, first['grant_id'], command)
    assert replayed['invitation_url'] is None and replayed['invitation_id'] == result['invitation_id']
    assert first['client'].get('/api/v1/portal/me').status_code == 200
    assert first['client'].post('/api/v1/portal/accept', json={'token': token, 'password': 'AnotherPortalPass789'}).status_code == 401


def test_password_recovery_checks_revision_revocation_and_internal_role(portal):
    first = portal['households'][0]
    current = next(row for row in admin.listing(store, portal['owner'].id)['items'] if row['id'] == first['grant_id'])
    payload = dict(expected_revision=current['identity_revision'], grant_revision=current['revision'],
        verification='Identität und persönliche Kontaktadresse unabhängig gegengeprüft.', idempotency_key=uuid4().hex)
    path = '/api/v1/portal-admin/grants/' + first['grant_id'] + '/recovery-invitation'
    assert first['client'].post(path, json=payload).status_code == 401
    stale = {**payload, 'expected_revision': current['identity_revision'] + 1}
    assert portal['office'].post(path, json=stale).status_code == 409
    admin.change_identity(store, portal['owner'].id, first['grant_id'], ChangeAccess(expected_revision=current['identity_revision'],
        active=False, reason='Zugang auf Wunsch der betroffenen Person gesperrt.', idempotency_key=uuid4().hex))
    payload['expected_revision'] += 1
    assert portal['office'].post(path, json=payload).status_code == 409


def test_two_households_are_isolated_from_search_preview_download_and_export(portal):
    first, second = portal["households"]
    doc, version = document(portal, first)
    assert first["client"].get("/api/v1/portal/me/documents").json()["items"] == []
    publication = publish(portal, first, version)
    root = f"/api/v1/portal/me/documents/{publication['id']}"
    assert len(first["client"].get("/api/v1/portal/me/documents?search=Haushalt").json()["items"]) == 1
    assert second["client"].get("/api/v1/portal/me/documents?search=Haushalt").json()["items"] == []
    for suffix in ("/download", "/preview"):
        assert first["client"].get(root + suffix).status_code == 200
        assert second["client"].get(root + suffix).status_code in (403, 404)
    own = first["client"].get("/api/v1/portal/me/export")
    assert own.status_code == 200
    with zipfile.ZipFile(io.BytesIO(own.content)) as bundle:
        assert len(json.loads(bundle.read("data.json"))["documents"]) == 1
    foreign = second["client"].get("/api/v1/portal/me/export")
    with zipfile.ZipFile(io.BytesIO(foreign.content)) as bundle:
        assert json.loads(bundle.read("data.json"))["documents"] == []
    with pytest.raises(HTTPException):
        publish(portal, second, version)
    assert first["client"].get(f"/api/v1/documents/{doc.id}").status_code == 401
    assert first["client"].get(doc.file_url).status_code == 401
    opaque = first["client"].cookies.get(common.COOKIE)
    assert first["client"].get("/api/v1/properties", headers={"Authorization": "Bearer " + opaque}).status_code == 401


def test_revocation_blocks_every_document_and_communication_route(portal):
    first, _ = portal["households"]
    _, version = document(portal, first)
    publication = publish(portal, first, version)
    case, command, _ = damage(first, image=True)
    detail = first["client"].get("/api/v1/portal/me/cases/" + case["id"]).json()
    image_id = detail["messages"][0]["attachments"][0]["id"]
    access = next(row for row in admin.listing(store, portal["owner"].id)["items"] if row["id"] == first["grant_id"])
    admin.change_access(store, portal["owner"].id, first["grant_id"], ChangeAccess(expected_revision=access["revision"], active=False,
        reason="Zugang auf ausdrücklichen Wunsch widerrufen.", idempotency_key=uuid4().hex))
    for route in (f"documents/{publication['id']}/download", f"documents/{publication['id']}/preview", "cases/" + case["id"], "attachments/" + image_id):
        assert first["client"].get("/api/v1/portal/me/" + route).status_code in (403, 404)
    assert first["client"].get("/api/v1/portal/me/documents").json()["items"] == []
    assert first["client"].get("/api/v1/portal/me/cases").json()["items"] == []
    assert first["client"].post("/api/v1/portal/me/cases", data={"command": json.dumps(command)}).status_code == 404


def test_damage_links_canonical_case_and_publishes_only_explicit_replies(portal):
    first, second = portal["households"]
    case, command, files = damage(first, image=True)
    repeated = first["client"].post("/api/v1/portal/me/cases", data={"command": json.dumps(command)}, files=files)
    assert repeated.json()["id"] == case["id"] and len(store.list_maintenance_cases()) == 1
    internal = portal["office"].get("/api/v1/portal-admin/cases").json()["items"][0]
    source = store.get_maintenance_case(internal["case_id"])
    assert source.unit_id == first["place"].id
    store.update_maintenance_case(source.id, MaintenanceCaseCreate(**{**source.model_dump(), "description": "INTERNAL-ONLY-NOTE", "assignee": "INTERNAL-EMPLOYEE"}))
    detail = first["client"].get("/api/v1/portal/me/cases/" + case["id"])
    assert "INTERNAL-ONLY" not in detail.text and "INTERNAL-EMPLOYEE" not in detail.text
    image_id = detail.json()["messages"][0]["attachments"][0]["id"]
    assert first["client"].get("/api/v1/portal/me/attachments/" + image_id).headers["content-type"] == "image/jpeg"
    assert second["client"].get("/api/v1/portal/me/attachments/" + image_id).status_code == 404
    assert second["client"].get("/api/v1/portal/me/cases/" + case["id"]).status_code == 404
    response = portal["office"].post(f"/api/v1/portal-admin/cases/{case['id']}/messages", json={"expected_revision": 1,
        "idempotency_key": uuid4().hex, "body": "Bitte ein Foto vom unteren Rahmen ergänzen."})
    assert response.status_code == 201, response.text
    assert "unteren Rahmen" in first["client"].get("/api/v1/portal/me/cases/" + case["id"]).text
    stale = first["client"].post(f"/api/v1/portal/me/cases/{case['id']}/messages", data={"command": json.dumps({"expected_revision": 1,
        "idempotency_key": uuid4().hex, "body": "Veraltete Antwort"})})
    assert stale.status_code == 409


def test_invitation_is_one_use_hashed_and_expiry_is_enforced(portal):
    first = portal["households"][0]
    invitation = first["invitation"]
    secret = invitation["invitation_url"].split("#")[1]
    assert first["client"].post("/api/v1/portal/accept", json={"token": secret, "password": "PortalPassword123"}).status_code == 401
    with common.raw_work(store) as unit:
        row = db.row(unit, pm.PortalInvitationORM, invitation["invitation_id"])
        assert row.token_sha256 == common.token_hash(secret) and secret not in str(db.values(row))
        db.put(unit, pm.PortalInvitationORM, {**db.values(row), "consumed_at": None, "expires_at": db.now() - timedelta(minutes=1)})
    assert first["client"].post("/api/v1/portal/accept", json={"token": secret, "password": "PortalPassword123"}).status_code == 401


def test_https_origin_cookie_isolation_and_durable_rate_limit(portal, monkeypatch):
    first = portal["households"][0]
    cookie = first["client"].cookies.get(common.COOKIE)
    unsafe = TestClient(app, base_url="http://portal.example.test", headers=HEADERS)
    assert unsafe.get("/api/v1/portal/me", cookies={common.COOKIE: cookie}).status_code == 403
    assert first["client"].post("/api/v1/portal/logout", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert first["client"].get("/api/v1/portal/me", headers={"Authorization": "Bearer " + auth.create_access_token(portal["owner"].id)}).status_code == 401
    for _ in range(6):
        response = first["client"].post("/api/v1/portal/login", json={"email": "nobody@example.test", "password": "incorrect"})
        assert response.status_code == 401
    response = first["client"].post("/api/v1/portal/login", json={"email": "nobody@example.test", "password": "incorrect"})
    assert response.status_code == 429 and response.headers["retry-after"] == "900"
    monkeypatch.setattr(settings, "portal_public_url", "http://127.0.0.1:8080")
    local = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 12345))
    assert local.get("/api/v1/portal/me").status_code == 503
    monkeypatch.setattr(settings, "portal_local_test_mode", True)
    assert local.get("/api/v1/portal/me").status_code == 401


def test_multiple_owners_require_separate_publications_and_no_tenant_documents(portal):
    owner_grants = []
    for index in (1, 2):
        person = store.create_contact(ContactCreate(contact_type="owner", first_name=f"Owner {index}", email=f"owner{index}@example.test"))
        share = ownership.create_share(store, OwnershipShareCreate(property_id=portal["prop"].id, owner_contact_id=person.id, share_percent=50), portal["owner"].id)
        invited = admin.invite(store, portal["owner"].id, InviteParty(kind="owner", party_id=person.id, relation_id=share.id, email=str(person.email),
            verification="Eigentumsnachweis und Identität geprüft.", idempotency_key=uuid4().hex))
        client = TestClient(app, base_url=ORIGIN, headers=HEADERS)
        response = client.post("/api/v1/portal/accept", json={"token": invited["invitation_url"].split("#")[1], "password": "OwnerPassword123"})
        assert response.status_code == 200, response.text
        owner_grants.append({"client": client, "grant_id": invited["grant"]["id"]})
    _, version = document(portal)
    publish(portal, owner_grants[0], version)
    assert len(owner_grants[0]["client"].get("/api/v1/portal/me/documents").json()["items"]) == 1
    assert owner_grants[1]["client"].get("/api/v1/portal/me/documents").json()["items"] == []
    _, personal = document(portal, portal["households"][0])
    with pytest.raises(HTTPException) as denied:
        publish(portal, owner_grants[0], personal)
    assert denied.value.status_code == 403


def test_contract_reassignment_and_identity_deactivation_block_existing_session(portal):
    first, second = portal["households"]
    _, version = document(portal, first)
    publication = publish(portal, first, version)
    store.update_contract(first["contract"].id, ContractCreate(**{**first["contract"].model_dump(), "tenant_id": second["tenant"].id}))
    assert first["client"].get("/api/v1/portal/me/documents").json()["items"] == []
    assert first["client"].get(f"/api/v1/portal/me/documents/{publication['id']}/download").status_code == 409
    current = next(row for row in admin.listing(store, portal["owner"].id)["items"] if row["id"] == first["grant_id"])
    admin.change_identity(store, portal["owner"].id, first["grant_id"], ChangeAccess(expected_revision=current["identity_revision"], active=False,
        reason="Konto nach Identitätsprüfung vollständig deaktiviert.", idempotency_key=uuid4().hex))
    assert first["client"].get("/api/v1/portal/me").status_code == 401
    assert first["client"].post("/api/v1/portal/login", json={"email": first["tenant"].email, "password": "PortalPassword123"}).status_code == 401


def test_hostile_images_are_atomic_and_concurrent_retries_create_one_case(portal):
    from concurrent.futures import ThreadPoolExecutor
    first = portal["households"][0]
    case, command, files = damage(first, image=True)
    before = len(store.list_maintenance_cases())
    invalid = {**command, "idempotency_key": uuid4().hex}
    response = first["client"].post("/api/v1/portal/me/cases", data={"command": json.dumps(invalid)},
        files=[*files, ("files", ("hidden.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/jpeg"))])
    assert response.status_code == 422 and len(store.list_maintenance_cases()) == before
    cookie = first["client"].cookies.get(common.COOKIE)
    simultaneous = {**command, "idempotency_key": uuid4().hex}
    def submit():
        client = TestClient(app, base_url=ORIGIN, headers=HEADERS, cookies={common.COOKIE: cookie})
        try:
            return client.post("/api/v1/portal/me/cases", data={"command": json.dumps(simultaneous)}, files=files)
        finally:
            client.close()
            from backend.dependencies import cleanup_session
            cleanup_session()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(), range(2)))
    assert all(row.status_code == 201 for row in responses), [row.text for row in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"] and len(store.list_maintenance_cases()) == before + 1


def test_case_publication_is_explicit_revision_bound_and_scoped(portal):
    first, second = portal["households"]
    case = store.create_maintenance_case(MaintenanceCaseCreate(property_id=portal["prop"].id, unit_id=first["place"].id,
        title="Interne Schadenakte", description="Streng interne Beschreibung"))
    grant_row = next(row for row in admin.listing(store, portal["owner"].id)["items"] if row["id"] == first["grant_id"])
    command = {"grant_revision": grant_row["revision"], "case_id": case.id, "case_updated_at": case.updated_at.isoformat(),
        "title": "Ihr Fenster wird geprüft", "reason": "Eigene Schadenakte der Partei geprüft und ausdrücklich freigegeben.", "idempotency_key": uuid4().hex}
    assert first["client"].get("/api/v1/portal/me/cases").json()["items"] == []
    wrong = portal["office"].post(f"/api/v1/portal-admin/grants/{second['grant_id']}/cases", json=command)
    assert wrong.status_code == 403
    stale = {**command, "case_updated_at": "2001-01-01T00:00:00Z", "idempotency_key": uuid4().hex}
    assert portal["office"].post(f"/api/v1/portal-admin/grants/{first['grant_id']}/cases", json=stale).status_code == 409
    response = portal["office"].post(f"/api/v1/portal-admin/grants/{first['grant_id']}/cases", json=command)
    assert response.status_code == 201, response.text
    result = first["client"].get("/api/v1/portal/me/cases")
    assert result.json()["total"] == 1 and "Streng interne Beschreibung" not in result.text
    limited = auth.register_user("limited-portal", "limited-portal@example.test", "Scoped manager", "ScopedPortal123", "verwalter", portfolio_access="selected", portfolio_ids=[])
    office = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(limited.id)})
    assert office.get("/api/v1/portal-admin/grants").json()["items"] == []
    denied = office.get(f"/api/v1/portal-admin/cases/{response.json()['id']}")
    assert denied.status_code in (403, 404)


def test_portal_customer_export_roundtrip_preserves_evidence_without_credentials(portal):
    import test_customer_portability as customer

    from backend.data_transfer_models import BatchOptions, CommitImport
    from backend.services.data_transfer import imports, portable_archive
    from backend.services.external_portal import service
    first = portal["households"][0]
    _, version = document(portal, first)
    publication = publish(portal, first, version)
    case, _, _ = damage(first, image=True)
    old = service.internal_detail(store, portal["owner"].id, case["id"])
    content, _ = customer.export((portal["owner"], portal["portfolio"], portal["office"]))
    _, evidence, _, _, _ = portable_archive.read(content)
    for record in evidence:
        assert record["source_type"] not in ("external_portal_sessions", "external_portal_invitations", "external_portal_commands")
        if record["source_type"] == "external_portal_identities":
            assert record["payload"]["password_hash"] is None and not record["payload"]["active"]
    purge()
    new_owner = auth.register_user("new-portal-office", "new@example.test", "New office", "NewPortalOffice123", "eigentuemer")
    batch = imports.create(store, new_owner.id, [("customer.zip", content)], BatchOptions(source_system="Portalwechsel"), uuid4().hex)
    assert batch["state"] == "ready", batch["preview"]
    result = imports.commit(store, new_owner.id, batch["id"], CommitImport(expected_revision=1, idempotency_key=uuid4().hex,
        acknowledge_warnings=True, reason="Portalnachrichten, Bilder, Zuordnungen und Originalhashes abgeglichen."))
    assert result["state"] == "committed"
    with common.admin_work(store, new_owner.id) as unit:
        pub = db.row(unit, pm.PortalPublicationORM, publication["id"])
        assert pub.sha256 == version.sha256 and not pub.active
        assert all(not row.active and row.password_hash is None for row in common.rows(unit, pm.PortalIdentityORM))
        assert common.rows(unit, pm.PortalSessionORM) == [] and common.rows(unit, pm.PortalInvitationORM) == []
    new = service.internal_detail(store, new_owner.id, case["id"])
    assert new["messages"] == old["messages"]
    picture = new["messages"][0]["attachments"][0]
    assert service.internal_attachment(store, new_owner.id, picture["id"])[0].startswith(b"\xff\xd8\xff")
    assert first["client"].post("/api/v1/portal/login", json={"email": first["tenant"].email, "password": "PortalPassword123"}).status_code == 401


def test_rate_limited_address_cannot_fill_storage_with_random_accounts(portal):
    from backend.services.external_portal.authentication import reserve_attempt
    for number in range(30):
        reserve_attempt(store, f"random-{number}", "192.0.2.1")
    with common.raw_work(store) as unit:
        before = len(common.rows(unit, pm.PortalAttemptORM))
    for number in range(5):
        with pytest.raises(HTTPException) as blocked:
            reserve_attempt(store, f"blocked-new-{number}", "192.0.2.1")
        assert blocked.value.status_code == 429
    with common.raw_work(store) as unit:
        assert len(common.rows(unit, pm.PortalAttemptORM)) == before
