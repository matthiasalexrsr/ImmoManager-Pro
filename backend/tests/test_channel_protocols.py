"""Independent byte, protocol and durable channel oracles; no live requests."""

import hashlib
import hmac
import io
import json
import zipfile
from uuid import uuid4

import httpx
import pytest
from archive_helpers import lease_with_document
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import DocumentCreate, ListingCreate, ListingPhotoCreate, MessageThreadCreate
from backend.services import aktenwerk
from backend.services import channel_workflows as flow
from backend.services.file_storage import get_file_storage
from backend.services.integrations.connection_types import ConnectionCreate
from backend.services.integrations.connections import Connections
from backend.services.integrations.manager import integration_manager
from backend.services.portal_adapter import ImmobilienScout24Adapter, OpenImmoFtpAdapter, ProtocolError, _oauth1_header
from backend.services.whatsapp_channel import WhatsAppAdapter, advance_status, challenge

PDF = b"%PDF-1.4\nEXACT ORIGINAL\x00\xff"
PNG = b"\x89PNG\r\n\x1a\nEXACT PHOTO\x00\xff"
WA = {
    "phone_number_id": "123456",
    "graph_version": "v26.0",
    "api_token": "SYNTHETIC-TOKEN",
    "app_secret": "SYNTHETIC-APP",
    "verify_token": "SYNTHETIC-VERIFY",
}
IS = {
    "default_portal": "is24",
    "consumer_key": "synthetic-consumer",
    "consumer_secret": "synthetic-secret",
    "access_token": "synthetic-token",
    "access_token_secret": "synthetic-token-secret",
    "sandbox": True,
}
PARAMS = {
    "to": "+491701234567",
    "template_name": "mietinformation",
    "language_code": "de_DE",
    "components": [{"type": "body", "parameters": [{"type": "text", "text": "Frau Müller"}]}],
    "opt_in": True,
    "opt_in_evidence": "Einwilligung vom 15.10.2026",
}


@pytest.fixture
def estate():
    owner = auth.register_user(
        "channels-" + uuid4().hex,
        "channels-" + uuid4().hex + "@example.test",
        "Kanalprüfung",
        "Secret123",
        "eigentuemer",
    )
    name = "documents/channel-" + uuid4().hex + ".pdf"
    get_file_storage().save(name, io.BytesIO(PDF), content_type="application/pdf")
    lease = lease_with_document(store, number=uuid4().hex, file_url="/uploads/" + name)
    listing = store.create_listing(ListingCreate(unit_id=lease["unit"].id, title="Prüfwohnung", target_rent=650))
    photo_name = "photos/channel-" + uuid4().hex + ".png"
    get_file_storage().save(photo_name, io.BytesIO(PNG), content_type="image/png")
    photo = store.create_listing_photo(
        ListingPhotoCreate(listing_id=listing.id, file_url="/uploads/" + photo_name, title="Küche", is_primary=True)
    )
    thread = store.create_message_thread(MessageThreadCreate(subject="Prüffaden", property_id=lease["property"].id))
    return {**lease, "owner": owner, "listing": listing, "photo": photo, "thread": thread}


def connect(estate, channel="whatsapp", config=None):
    return Connections(store, integration_manager).create(
        ConnectionCreate(
            idempotency_key=uuid4().hex,
            provider_id=channel,
            name="Synthetischer Zugang",
            config=config or WA,
            enabled=True,
        ),
        estate["owner"].id,
    )


def prepare(estate, channel, source, parameters=None, connection=None):
    preview = flow.source_preview(store, estate["owner"].id, channel, source)
    payload = flow.Prepare(
        idempotency_key=uuid4().hex,
        source_sha256=preview["source_sha256"],
        parameters=parameters or {},
        connection_id=connection["id"] if connection else None,
        connection_revision=connection["revision"] if connection else None,
    )
    return flow.prepare(store, estate["owner"].id, channel, source, payload), payload


def command(case, action, **params):
    return flow.Action(idempotency_key=uuid4().hex, base_revision=case["revision"], action=action, parameters=params)


def test_whatsapp_exact_template_acceptance_and_unknown():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.SYNTHETIC"}]})

    adapter = WhatsAppAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    result = adapter.send(PARAMS, WA)
    assert result == {"status": "accepted", "external_id": "wamid.SYNTHETIC", "delivery_confirmed": False}
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == "https://graph.facebook.com/v26.0/123456/messages"
    assert body["to"] == "491701234567" and body["template"] == {
        "name": "mietinformation",
        "language": {"code": "de_DE"},
        "components": PARAMS["components"],
    }
    assert "opt_in" not in body and "SYNTHETIC-TOKEN" not in json.dumps(result)
    for status in (401, 403, 429, 500):
        rejecting = WhatsAppAdapter(
            httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"error": {"code": 10}})))
        )
        with pytest.raises(ProtocolError) as exc:
            rejecting.send(PARAMS, WA)
        assert exc.value.state == ("unknown" if status >= 500 else "failed")
    with pytest.raises(ValueError):
        adapter.send({**PARAMS, "opt_in": False}, WA)
    missing = WhatsAppAdapter(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"messages": []})))
    )
    with pytest.raises(ProtocolError, match="Nachrichtenkennung"):
        missing.send(PARAMS, WA)


def test_media_multipart_and_hash_oracle():
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "987"})
        if request.url.host == "graph.facebook.com":
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/media/987",
                    "sha256": hashlib.sha256(PDF).hexdigest(),
                    "mime_type": "application/pdf",
                },
            )
        return httpx.Response(200, content=PDF)

    adapter = WhatsAppAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    assert adapter.upload(PDF, "Original.pdf", "application/pdf", WA)["id"] == "987"
    assert PDF in calls[0].content and b'name="messaging_product"' in calls[0].content
    assert adapter.receive_media("987", WA)[0] == PDF
    with pytest.raises(ValueError):
        adapter.upload(b"wrong", "x.pdf", "application/pdf", WA)


def test_webhook_hmac_challenge_mixed_status_and_replay(estate):
    connection = connect(estate)
    case, _ = prepare(estate, "whatsapp", estate["thread"].id, PARAMS, connection)

    class Adapter:
        def send(self, payload, config):
            return {"status": "accepted", "external_id": "wamid.SIGNED", "delivery_confirmed": False}

    accepted = flow.execute(store, estate["owner"].id, case["id"], command(case, "send"), whatsapp=Adapter())
    assert accepted["state"] == "accepted" and accepted["progress"]["delivery_confirmed"] is False
    statuses = [
        {
            "id": "wamid.SIGNED",
            "status": status,
            "timestamp": str(100 + i),
            "recipient_id": "491701234567",
            "biz_opaque_callback_data": case["id"],
        }
        for i, status in enumerate(("read", "delivered", "failed", "sent"))
    ]
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {"metadata": {"phone_number_id": "123456"}, "statuses": statuses},
                        }
                    ]
                }
            ],
        }
    ).encode()
    signature = "sha256=" + hmac.new(WA["app_secret"].encode(), raw, hashlib.sha256).hexdigest()
    assert flow.receive_webhook(store, connection["id"], raw, signature) == {"received": True, "replayed": False}
    result = flow.get(store, estate["owner"].id, case["id"])
    assert result["state"] == "read"
    assert result["progress"]["delivery_confirmed"] is True
    assert flow.receive_webhook(store, connection["id"], raw, signature)["replayed"] is True
    assert flow.get(store, estate["owner"].id, case["id"])["revision"] == result["revision"]
    with pytest.raises(ProtocolError):
        flow.receive_webhook(store, connection["id"], raw + b" ", signature)
    assert challenge("subscribe", "SYNTHETIC-VERIFY", "abc", "SYNTHETIC-VERIFY") == "abc"
    with pytest.raises(ProtocolError):
        challenge("subscribe", "wrong", "abc", "SYNTHETIC-VERIFY")


def test_post_requires_supplied_purchased_original_then_manual_post(estate):
    actor = estate["owner"].id
    case, payload = prepare(
        estate,
        "post",
        estate["document"].id,
        {"recipient_name": "Mia Muster", "street": "Prüfweg 1", "postcode": "01099", "city": "Dresden"},
    )
    assert flow.prepare(store, actor, "post", estate["document"].id, payload)["replayed"]
    with pytest.raises(HTTPException):
        flow.post_action(store, actor, case["id"], command(case, "posted", manually_posted_confirmed=True))
    with pytest.raises(HTTPException):
        flow.post_action(
            store,
            actor,
            case["id"],
            command(
                case,
                "frank",
                document_id=estate["document"].id,
                purchased_original_confirmed=True,
                purchase_reference="P-1",
            ),
        )
    key = "documents/postage-" + uuid4().hex + ".pdf"
    purchased = b"%PDF-1.7\nSUPPLIED PURCHASED ORIGINAL"
    get_file_storage().save(key, io.BytesIO(purchased), content_type="application/pdf")
    document = store.create_document(
        DocumentCreate(property_id=estate["property"].id, title="Gekaufte Marke", file_url="/uploads/" + key)
    )
    frank = command(
        case, "frank", document_id=document.id, purchased_original_confirmed=True, purchase_reference="Kauf 2026-10-16"
    )
    franked = flow.post_action(store, actor, case["id"], frank)
    assert franked["state"] == "franked"
    assert flow.post_action(store, actor, case["id"], frank)["replayed"]
    with flow.work(store, actor) as unit:
        row = flow.require_case(unit, case["id"])
        assert flow.read_bytes(unit, row, franked["progress"]["purchased_original"]) == purchased
        assert flow.read_bytes(unit, row, franked["snapshot"]["originals"][0]) == PDF
    posted = flow.post_action(store, actor, case["id"], command(franked, "posted", manually_posted_confirmed=True))
    assert posted["state"] == "posted" and posted["progress"]["delivery_confirmed"] is False
    assert get_file_storage().get(key) == purchased


def test_restart_unknown_blocks_second_send_and_cas(estate):
    connection = connect(estate)
    actor = estate["owner"].id
    case, _ = prepare(estate, "whatsapp", estate["thread"].id, PARAMS, connection)

    class Crash:
        calls = 0

        def send(self, payload, config):
            self.calls += 1
            raise RuntimeError("SYNTHETIC PROCESS DEATH")

    adapter = Crash()
    payload = command(case, "send")
    with pytest.raises(RuntimeError):
        flow.execute(store, actor, case["id"], payload, whatsapp=adapter)
    recovered = flow.get(store, actor, case["id"])
    assert recovered["state"] == "unknown"
    assert flow.execute(store, actor, case["id"], payload, whatsapp=adapter)["state"] == "unknown"
    assert adapter.calls == 1
    with pytest.raises(HTTPException):
        flow.execute(store, actor, case["id"], command(recovered, "send"), whatsapp=adapter)
    with pytest.raises(HTTPException):
        flow.execute(store, actor, case["id"], command(case, "send"), whatsapp=adapter)


def test_source_photo_bytes_and_scope_revoke(estate, monkeypatch):
    connection = connect(estate, "listing-portals", IS)
    actor = estate["owner"].id
    case, _ = prepare(estate, "is24", estate["listing"].id, {}, connection)
    info = case["snapshot"]["originals"][0]
    assert info["sha256"] == hashlib.sha256(PNG).hexdigest()
    storage = get_file_storage()
    original_get = storage.get
    photo_key = estate["photo"].file_url.removeprefix("/uploads/")
    monkeypatch.setattr(storage, "get", lambda key: PNG + b"changed" if key == photo_key else original_get(key))
    with pytest.raises(HTTPException, match="Quelle verändert"):
        flow.execute(store, actor, case["id"], command(case, "publish"))
    foreign = auth.register_user(
        "foreign-" + uuid4().hex,
        "foreign-" + uuid4().hex + "@example.test",
        "Fremd",
        "Secret123",
        "verwalter",
        portfolio_access="selected",
        portfolio_ids=[],
    )
    with pytest.raises(HTTPException) as exc:
        flow.get(store, foreign.id, case["id"])
    assert exc.value.status_code == 404


def test_is24_actual_authorized_multipart_and_publish_status():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/attachment/"):
            return httpx.Response(201, json={"common.messages": {"message": [{"id": "photo-1"}]}})
        if request.url.path.endswith("/realestate/"):
            return httpx.Response(201, json={"common.messages": {"message": [{"id": "123456"}]}})
        return httpx.Response(200, json={})

    adapter = ImmobilienScout24Adapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    listing = {
        "external_id": "local-1",
        "title": "Wohnung",
        "target_rent": 650,
        "area_sqm": 50,
        "rooms": 2,
        "address": {"street": "Prüfweg", "house_number": "1", "postcode": "01099", "city": "Dresden"},
    }
    identifier = adapter.create(listing, IS)
    assert identifier == "123456"
    photo = {
        "id": "photo-1",
        "name": "kueche.png",
        "sha256": hashlib.sha256(PNG).hexdigest(),
        "media_type": "image/png",
        "title": "Küche",
    }
    adapter.upload_photo(identifier, photo, PNG, IS)
    adapter.write("publish", identifier, listing, IS)
    upload = requests[1]
    assert upload.headers["authorization"].startswith("OAuth ")
    assert b'name="attachment"' in upload.content and b'name="metadata"' in upload.content and PNG in upload.content
    assert b"externalCheckSum" in upload.content and photo["sha256"].encode() in upload.content
    assert requests[2].url.path.endswith("/publish")
    assert json.loads(requests[2].content)["common.publishObject"]["realEstate"]["@id"] == identifier
    with pytest.raises(ProtocolError):
        adapter.upload_photo(identifier, photo, PNG + b"bad", IS)


def test_openimmo_exact_local_images_zip_and_ftps_transfer_distinct():
    from xml.etree import ElementTree as ET

    config = {
        "provider_number": "123",
        "company_name": "Prüfung",
        "ftp_host": "synthetic.example.test",
        "ftp_username": "u",
        "ftp_password": "p",
    }
    listing = {
        "external_id": "stable-1",
        "title": "Prüfung & Küche",
        "target_rent": 650,
        "area_sqm": 50,
        "rooms": 2,
        "address": {"postcode": "01099", "city": "Dresden"},
    }
    photo = {"sha256": hashlib.sha256(PNG).hexdigest(), "media_type": "image/png", "title": "Küche"}

    class FTP:
        def __init__(self):
            self.protected = False
            self.commands = []

        def connect(self, *args):
            pass

        def login(self, *args):
            pass

        def prot_p(self):
            self.protected = True

        def storbinary(self, command, buffer):
            self.commands.append((command, buffer.read()))

        def close(self):
            pass

    ftp = FTP()
    adapter = OpenImmoFtpAdapter(ftp_factory=lambda: ftp)
    packet = adapter.package(listing, [(photo, PNG)], "NEW", config)
    archive = zipfile.ZipFile(io.BytesIO(packet))
    xml = ET.fromstring(archive.read("openimmo.xml"))
    transfer = xml.find("uebertragung")
    assert transfer is not None and transfer.attrib["version"] == "1.2.7"
    attachment = xml.find(".//anhang")
    assert attachment is not None and attachment.attrib["location"] == "LOCAL"
    path = attachment.find("daten/pfad")
    assert path is not None and path.text is not None
    assert archive.read(path.text) == PNG
    object_id = xml.find(".//verwaltung_techn/openimmo_obid")
    assert object_id is not None and object_id.text == "stable-1"
    assert adapter.package(listing, [(photo, PNG)], "NEW", config) == packet
    result = adapter.transfer(packet, config)
    assert ftp.protected and ftp.commands[0][1] == packet
    assert result["status"] == "transferred" and result["publication_confirmed"] is False


@pytest.mark.parametrize(
    "status,receipt,expected",
    [
        (409, {"id": "a"}, "conflict"),
        (409, {"id": "a", "exchange_id": "wrong", "sha256": "bad"}, "conflict"),
        (201, {"id": "a"}, "unknown"),
        (
            409,
            {"id": "a", "exchange_id": "immomanager:document:one", "sha256": hashlib.sha256(PDF).hexdigest()},
            "already_present",
        ),
    ],
)
def test_aktenwerk_receipt_never_accepts_unconfirmed_identity_or_bytes(monkeypatch, status, receipt, expected):
    monkeypatch.setattr(aktenwerk, "read_file", lambda *args: (PDF, "one.pdf"))
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=receipt)

    entry = aktenwerk.Entry("immomanager:document:one", "vertrag", "Original", None, "/uploads/one.pdf")
    result = aktenwerk.send_entries(
        None,
        [entry],
        {"base_url": "https://synthetic.example.test", "api_token": "synthetic"},
        "actor",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result["results"][0]["status"] == expected
    assert result["sent"] == int(expected == "already_present")
    assert PDF in requests[0].content
    assert requests[0].headers["Idempotency-Key"] == "immomanager:document:one:" + hashlib.sha256(PDF).hexdigest()


def test_scoped_post_http_and_original_access(estate):
    selected = auth.register_user(
        "scoped-" + uuid4().hex,
        "scoped-" + uuid4().hex + "@example.test",
        "Sachbearbeitung",
        "Secret123",
        "buchhaltung",
        portfolio_access="selected",
        portfolio_ids=[estate["portfolio"].id],
    )
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(selected.id)})
    preview = client.get("/api/v1/documents/" + estate["document"].id + "/post/preview")
    assert preview.status_code == 200, preview.text
    payload = {
        "idempotency_key": uuid4().hex,
        "source_sha256": preview.json()["source_sha256"],
        "parameters": {"recipient_name": "Mia", "street": "Test 1", "postcode": "01099", "city": "Dresden"},
    }
    prepared = client.post("/api/v1/messages/channels/post/" + estate["document"].id + "/prepare", json=payload)
    assert prepared.status_code == 200, prepared.text
    case = prepared.json()
    original = case["snapshot"]["originals"][0]
    downloaded = client.get(
        "/api/v1/messages/channel-cases/" + case["id"] + "/original", params={"name": original["evidence_name"]}
    )
    assert downloaded.status_code == 200 and downloaded.content == PDF
    # A fresh issued token does not freeze portfolio authority.
    auth.update_user(selected.id, {"portfolio_access": "selected", "portfolio_ids": []})
    assert client.get("/api/v1/messages/channel-cases/" + case["id"]).status_code == 404


def test_http_public_webhook_and_private_options(estate):
    connection = connect(estate)
    client = TestClient(app)
    url = "/api/v1/channel-webhooks/whatsapp/" + connection["id"]
    assert (
        client.get(
            url, params={"hub.mode": "subscribe", "hub.verify_token": WA["verify_token"], "hub.challenge": "731"}
        ).text
        == "731"
    )
    assert (
        client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "bad", "hub.challenge": "731"}).status_code
        == 403
    )
    assert client.post(url, content=b"{}", headers={"X-Hub-Signature-256": "invalid"}).status_code == 403
    signed = b'{"object":"whatsapp_business_account","entry":[]}'
    signature = "sha256=" + hmac.new(WA["app_secret"].encode(), signed, hashlib.sha256).hexdigest()
    assert client.post(url, content=signed, headers={"X-Hub-Signature-256": signature}).json()["received"] is True
    assert client.get("/api/v1/messages/channel-options?channel=whatsapp").status_code == 401
    owner = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(estate["owner"].id)})
    options = owner.get("/api/v1/messages/channel-options?channel=whatsapp")
    assert options.status_code == 200 and connection["id"] in {item["id"] for item in options.json()}
    assert not any(value in options.text for value in WA.values() if value.startswith("SYNTHETIC"))


def test_actual_official_array_envelope_oauth_vector_and_exact_status(monkeypatch):
    import backend.services.portal_adapter as protocol

    monkeypatch.setattr(protocol.secrets, "token_hex", lambda n: "kllo9940pd9333jh")
    monkeypatch.setattr(protocol.time, "time", lambda: 1191242096)
    cfg = {
        "consumer_key": "dpf43f3p2l4k3l03",
        "consumer_secret": "kd94hf93k423kf44",
        "access_token": "nnch734d00sl2jdk",
        "access_token_secret": "pfkkdhi9sl3r4s00",
    }
    header = _oauth1_header("GET", "http://photos.example.net/photos?file=vacation.jpg&size=original", cfg)
    assert 'oauth_signature="tR3%2BTy81lMeYAr%2FFid0kMTYa%2FWM%3D"' in header

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                201,
                json={"common.messages": [{"message": {"id": 62558084, "messageCode": "MESSAGE_RESOURCE_CREATED"}}]},
            )
        return httpx.Response(
            200,
            json={
                "common.publishObjects": {
                    "publishObject": [{"realEstate": {"@id": "62558084"}, "publishChannel": {"@id": "10000"}}]
                }
            },
        )

    adapter = ImmobilienScout24Adapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    listing = {
        "external_id": "local",
        "title": "Wohnung",
        "target_rent": 650,
        "area_sqm": 50,
        "rooms": 2,
        "address": {"street": "Test", "house_number": "1", "postcode": "01099", "city": "Dresden"},
    }
    assert adapter.create(listing, IS) == "62558084"
    assert adapter.check_status("62558084", IS)["status"] == "published"
    with pytest.raises(ProtocolError):
        adapter.check_status("DIFFERENT", IS)


def test_is24_timeout_reconcile_resumes_exact_photo_without_duplicate_create(estate):
    connection = connect(estate, "listing-portals", IS)
    actor = estate["owner"].id
    case, _ = prepare(estate, "is24", estate["listing"].id, {}, connection)

    class Adapter:
        creates = 0
        uploads = 0
        publishes = 0

        def create(self, listing, config):
            self.creates += 1
            return "external-731"

        def upload_photo(self, identifier, info, content, config):
            assert identifier == "external-731" and content == PNG
            self.uploads += 1
            if self.uploads == 1:
                raise ProtocolError("unknown", "SYNTHETIC LOST UPLOAD RESPONSE")

        def write(self, action, identifier, listing, config):
            self.publishes += int(action == "publish")

        def check_status(self, identifier, config):
            return {"status": "unpublished"}

        def reconcile_photo(self, identifier, photo, config):
            return True

    adapter = Adapter()
    unknown = flow.execute(store, actor, case["id"], command(case, "publish"), is24=adapter)
    assert unknown["state"] == "unknown" and unknown["external_id"] == "external-731" and adapter.publishes == 0
    recovered = flow.execute(store, actor, case["id"], command(unknown, "reconcile"), is24=adapter)
    assert recovered["state"] == "prepared"
    published = flow.execute(store, actor, case["id"], command(recovered, "publish"), is24=adapter)
    assert published["state"] == "published"
    assert (adapter.creates, adapter.uploads, adapter.publishes) == (1, 1, 1)


def test_aktenwerk_restart_unknown_only_status_reconcile_no_blind_post(estate):
    actor = estate["owner"].id
    entries, _ = aktenwerk.select_for_transfer(store, ["immomanager:document:" + estate["document"].id])
    calls = []
    config = {"base_url": "https://synthetic-dms.example.test", "receipt_status_supported": True}

    def lost(request):
        calls.append(request)
        raise httpx.ReadTimeout("SYNTHETIC LOST RESPONSE", request=request)

    first = aktenwerk.send_entries(store, entries, config, actor, httpx.Client(transport=httpx.MockTransport(lost)))
    assert first["results"][0]["status"] == "unknown"

    def status(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.params["sha256"] == hashlib.sha256(PDF).hexdigest()
        return httpx.Response(
            200,
            json={"id": "dms-731", "exchange_id": entries[0].exchange_id, "sha256": hashlib.sha256(PDF).hexdigest()},
        )

    second = aktenwerk.send_entries(store, entries, config, actor, httpx.Client(transport=httpx.MockTransport(status)))
    assert second["results"][0]["status"] == "already_present" and second["sent"] == 1
    assert [r.method for r in calls] == ["POST", "GET"]


def test_manual_marketing_uses_existing_lead_viewing_contract_no_financial_writes(estate):
    from backend.services import marketing_workflows as marketing

    actor = estate["owner"].id
    listing = estate["listing"].id
    preview = flow.source_preview(store, actor, "is24", listing)

    def act(action, parameters):
        return marketing.action(
            store,
            actor,
            listing,
            marketing.MarketingAction(
                idempotency_key=uuid4().hex,
                source_sha256=preview["source_sha256"],
                action=action,
                parameters=parameters,
            ),
        )

    before = {name: len(getattr(store, "list_" + name)()) for name in ("bookings", "contracts")}
    lead = act("lead", {"full_name": "Ausdrücklich gewählte Partei"})["lead"]
    viewing = act(
        "viewing",
        {"lead_id": lead["id"], "lead_revision": lead["updated_at"], "scheduled_at": "2026-10-18T14:00:00+02:00"},
    )["viewing"]
    done = act(
        "complete_viewing",
        {
            "lead_id": lead["id"],
            "lead_revision": lead["updated_at"],
            "viewing_id": viewing["id"],
            "viewing_revision": viewing["updated_at"],
            "completed_confirmed": True,
        },
    )["viewing"]
    contract = store.get_contract(estate["contract"].id)
    params = {
        "lead_id": lead["id"],
        "lead_revision": lead["updated_at"],
        "viewing_id": done["id"],
        "viewing_revision": done["updated_at"],
        "contract_id": contract.id,
        "contract_revision": contract.updated_at.isoformat(),
        "tenant_id": contract.tenant_id,
        "contract_confirmed": True,
    }
    confirmed = act("confirm_contract", params)
    assert confirmed["confirmed_contract"]["contract_id"] == contract.id
    assert marketing.overview(store, actor, listing)["confirmations"][-1] == confirmed["confirmed_contract"]
    assert {name: len(getattr(store, "list_" + name)()) for name in before} == before
    with pytest.raises(HTTPException):
        act("confirm_contract", {**params, "tenant_id": "guessed-by-name"})


def test_signed_unsolicited_inbound_requires_explicit_thread_assignment(estate):
    connection = connect(estate)
    actor = estate["owner"].id
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "messages": [
                                    {
                                        "id": "wamid.RECEIVED",
                                        "from": "491709999999",
                                        "timestamp": "1792152000",
                                        "type": "text",
                                        "text": {"body": "Prüfung – keine automatische Zuordnung"},
                                    }
                                ],
                            },
                        }
                    ]
                }
            ],
        }
    ).encode()
    signature = "sha256=" + hmac.new(WA["app_secret"].encode(), raw, hashlib.sha256).hexdigest()
    flow.receive_webhook(store, connection["id"], raw, signature)
    assert flow.list_cases(store, actor, "whatsapp", estate["thread"].id)["items"] == []
    inbox = flow.inbox_page(store, actor, connection["id"])
    batch = inbox["items"][0]
    thread = store.get_message_thread(estate["thread"].id)
    payload = flow.InboundAssignment(
        idempotency_key=uuid4().hex,
        thread_id=thread.id,
        thread_revision=thread.updated_at.isoformat(),
        message_id="wamid.RECEIVED",
        confirmed=True,
    )
    case = flow.assign_inbound(store, actor, connection["id"], batch["id"], payload)
    assert case["state"] == "received" and case["source_id"] == thread.id
    assert flow.assign_inbound(store, actor, connection["id"], batch["id"], payload)["replayed"] is True
    assert flow.list_cases(store, actor, "whatsapp", thread.id)["items"][0]["snapshot"]["inbound"]["text"][
        "body"
    ].startswith("Prüfung")


def test_delivery_failure_never_regresses_read():
    assert advance_status("sent", "failed") == "failed"
    assert advance_status("failed", "sent") == "failed"
    assert advance_status("read", "failed") == "read"


@pytest.mark.parametrize("extra", [{"status": "failed"}, {"status": []}, {"schema": "other/1"}, {"file": {"sha256": "0" * 64}}])
def test_aktenwerk_identity_hash_do_not_override_negative_receipt(extra):
    receipt = {"id": "remote-1", "exchange_id": "source-1", "sha256": hashlib.sha256(PDF).hexdigest(), **extra}
    response = httpx.Response(201, json=receipt)
    assert aktenwerk._confirmed_receipt_id(response, "source-1", hashlib.sha256(PDF).hexdigest()) is None


def test_channel_case_listing_rechecks_original_portfolio_binding(estate):
    actor = estate["owner"].id
    case, _ = prepare(
        estate,
        "post",
        estate["document"].id,
        {"recipient_name": "Mia", "street": "Test 1", "postcode": "01099", "city": "Dresden"},
    )
    selected = auth.register_user(
        "limited-" + uuid4().hex,
        uuid4().hex + "@example.test",
        "Prüfung",
        "Secret123",
        "buchhaltung",
        portfolio_access="selected",
        portfolio_ids=[estate["portfolio"].id],
    )
    assert flow.list_cases(store, selected.id, "post", estate["document"].id)["items"][0]["id"] == case["id"]
    # Simulate a retained original binding that is outside the now-current grant.
    # Editing only encrypted fixture metadata exercises the historical-access guard.
    with flow.work(store, actor, "/messages") as unit:
        row = flow.require_case(unit, case["id"])
        frozen = flow.snapshot(row)
        frozen["context"]["portfolio_ids"] = ["revoked-original-portfolio"]
        data = flow.db.values(row)
        data["snapshot_token"] = flow.db.seal(frozen, "channel/" + row.id + "/snapshot")
        flow.db.put(unit, flow.Case, data)
    with pytest.raises(HTTPException) as error:
        flow.list_cases(store, selected.id, "post", estate["document"].id)
    assert error.value.status_code == 404


def test_invalid_template_is_validation_error_before_any_case_or_transport(estate):
    actor = estate["owner"].id
    connection = connect(estate)
    with pytest.raises(HTTPException) as error:
        prepare(estate, "whatsapp", estate["thread"].id, {**PARAMS, "opt_in": False}, connection)
    assert error.value.status_code == 422
    assert flow.list_cases(store, actor, "whatsapp", estate["thread"].id)["items"] == []
