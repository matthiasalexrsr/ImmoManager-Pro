"""Official IS24 OAuth1 and OpenImmo 1.2.7 transports.

No configuration is read here. Callers supply authorized frozen content and bytes,
and persist checkpoints BEFORE entering each potentially ambiguous write.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import ssl
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from ftplib import FTP_TLS
from io import BytesIO
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit
from xml.etree import ElementTree as ET

import httpx


@dataclass
class PortalPublishResult:
    success: bool
    portal_name: str
    portal_listing_id: str | None = None
    portal_url: str | None = None
    error: str | None = None
    published_at: datetime | None = None
    details: dict = field(default_factory=dict)


class ProtocolError(Exception):
    def __init__(self, state, message, status_code=None):
        self.state, self.status_code = state, status_code
        super().__init__(message)


def _oauth_escape(value: object) -> str:
    return quote(str(value), safe="~-._")


def _oauth1_header(method: str, url: str, config: dict) -> str:
    parts = urlsplit(url)
    oauth = {
        "oauth_consumer_key": config["consumer_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": config["access_token"],
        "oauth_version": "1.0",
    }
    params = [*parse_qsl(parts.query, keep_blank_values=True), *oauth.items()]
    normalized = "&".join(
        f"{_oauth_escape(key)}={_oauth_escape(value)}"
        for key, value in sorted(params, key=lambda item: (_oauth_escape(item[0]), _oauth_escape(item[1])))
    )
    base_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    signature_base = "&".join((_oauth_escape(method.upper()), _oauth_escape(base_url), _oauth_escape(normalized)))
    signing_key = f"{_oauth_escape(config['consumer_secret'])}&{_oauth_escape(config['access_token_secret'])}"
    digest = hmac.new(signing_key.encode(), signature_base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode()
    return "OAuth " + ", ".join(
        f'{_oauth_escape(key)}="{_oauth_escape(value)}"' for key, value in sorted(oauth.items())
    )


def checked(response, expected=(200, 201, 204), *, write=False):
    if response.status_code not in expected:
        state = "unknown" if write and response.status_code >= 500 else "failed"
        raise ProtocolError(state, f"Anbieter antwortete mit HTTP {response.status_code}.", response.status_code)
    if not response.content:
        return {}
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except ValueError:
        raise ProtocolError("unknown" if write else "failed", "Anbieterantwort ist nicht lesbar.") from None


class ImmobilienScout24Adapter:
    portal_name = "ImmobilienScout24"

    def __init__(self, api_key="", api_secret="", *, client=None):
        self.client = client
        self.api_key, self.api_secret = api_key, api_secret

    def is_configured(self, config=None):
        return all(
            (config or {}).get(k) for k in ("consumer_key", "consumer_secret", "access_token", "access_token_secret")
        )

    def request(self, method, path, config, **kwargs):
        if not self.is_configured(config):
            raise ProtocolError("failed", "IS24-Zugangsdaten sind unvollständig.")
        host = "rest.sandbox-immobilienscout24.de" if config.get("sandbox", True) else "rest.immobilienscout24.de"
        url = "https://" + host + "/restapi/api" + path
        try:
            return (self.client.request if self.client else httpx.request)(
                method,
                url,
                headers={"Accept": "application/json", "Authorization": _oauth1_header(method, url, config)},
                timeout=30,
                follow_redirects=False,
                **kwargs,
            )
        except httpx.HTTPError:
            raise ProtocolError(
                "unknown" if method != "GET" else "failed", "IS24-Antwort fehlt; vor Wiederholung abgleichen."
            ) from None

    @staticmethod
    def _realestate_payload(listing: dict) -> dict:
        address = listing.get("address") or {}
        base_rent = listing.get("target_rent")
        area = listing.get("area_sqm")
        rooms = listing.get("rooms")
        if base_rent is None or area is None or rooms is None:
            raise ValueError("IS24 benötigt Kaltmiete, Wohnfläche und Zimmerzahl.")
        required_address = ("street", "house_number", "postcode", "city")
        if any(not address.get(key) for key in required_address):
            raise ValueError("IS24 benötigt Straße, Hausnummer, PLZ und Ort.")

        body = {
            "externalId": str(listing["external_id"]),
            "title": listing["title"],
            "address": {
                "street": address["street"],
                "houseNumber": address["house_number"],
                "postcode": address["postcode"],
                "city": address["city"],
            },
            "realEstateState": "ACTIVE",
            "showAddress": "true",
            "apartmentType": "NO_INFORMATION",
            "lift": "false",
            "cellar": "NOT_APPLICABLE",
            "handicappedAccessible": "NOT_APPLICABLE",
            "condition": "NO_INFORMATION",
            "firingTypes": [{"firingType": "NO_INFORMATION"}],
            "energySourcesEnev2014": {"energySourceEnev2014": "NO_INFORMATION"},
            "energyConsumptionContainsWarmWater": "NOT_APPLICABLE",
            "guestToilet": "NOT_APPLICABLE",
            "baseRent": float(base_rent),
            "heatingCostsInServiceCharge": "NOT_APPLICABLE",
            "petsAllowed": "NO_INFORMATION",
            "useAsFlatshareRoom": "NOT_APPLICABLE",
            "livingSpace": float(area),
            "numberOfRooms": float(rooms),
            "builtInKitchen": "false",
            "balcony": "false",
            "certificateOfEligibilityNeeded": "false",
            "garden": "false",
            "courtage": {"hasCourtage": "NO"},
        }
        if listing.get("service_charge") is not None:
            body["serviceCharge"] = float(listing["service_charge"])
        if listing.get("description"):
            body["descriptionNote"] = listing["description"]
        if listing.get("features"):
            body["furnishingNote"] = listing["features"]
        return {"realestates.apartmentRent": body}

    def create(self, listing, config):
        data = checked(
            self.request("POST", "/offer/v1.0/user/me/realestate/", config, json=self._realestate_payload(listing)),
            write=True,
        )
        # IS24 message response has the resource id in the message's id, never a recursive arbitrary id.
        envelope = data.get("common.messages", {})
        messages = (
            envelope.get("message", [])
            if isinstance(envelope, dict)
            else [item.get("message", {}) for item in envelope if isinstance(item, dict)]
        )
        if isinstance(messages, dict):
            messages = [messages]
        identifier = next((str(m["id"]) for m in messages if m.get("id")), None)
        if not identifier:
            raise ProtocolError("unknown", "IS24 hat keine eindeutige Objektkennung bestätigt.")
        return identifier

    def upload_photo(self, identifier, photo, content, config):
        sha = hashlib.sha256(content).hexdigest()
        if sha != photo["sha256"]:
            raise ProtocolError("failed", "Bildbytes stimmen nicht mit der Vorschau überein.")
        metadata = ET.Element(
            "common:attachment",
            {
                "xmlns:common": "http://rest.immobilienscout24.de/schema/common/1.0",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:type": "common:Picture",
            },
        )
        for key, value in [
            ("title", photo.get("title", "Bild")[:30]),
            ("externalId", photo["id"]),
            ("externalCheckSum", sha),
            ("floorplan", "false"),
            ("titlePicture", str(photo.get("is_primary", False)).lower()),
        ]:
            ET.SubElement(metadata, key).text = value
        response = self.request(
            "POST",
            f"/offer/v1.0/user/me/realestate/{quote(identifier, safe='')}/attachment/",
            config,
            files={
                "attachment": (photo["name"], content, photo["media_type"], {"Content-Transfer-Encoding": "binary"}),
                "metadata": (
                    "body.xml",
                    ET.tostring(metadata, encoding="utf-8", xml_declaration=True),
                    "application/xml",
                ),
            },
        )
        return checked(response, write=True)

    def write(self, action, identifier, listing, config):
        identifier = quote(identifier, safe="")
        channel = quote(str(config.get("publish_channel") or "10000"), safe="")
        if action == "update":
            response = self.request(
                "PUT", f"/offer/v1.0/user/me/realestate/{identifier}", config, json=self._realestate_payload(listing)
            )
        elif action == "deactivate":
            response = self.request("DELETE", f"/offer/v1.0/publish/{identifier}_{channel}", config)
        elif action == "publish":
            response = self.request(
                "POST",
                "/offer/v1.0/publish",
                config,
                json={"common.publishObject": {"realEstate": {"@id": identifier}, "publishChannel": {"@id": channel}}},
            )
        else:
            raise ValueError("Unbekannte Portalaktion")
        return checked(response, write=True)

    def reconcile_object(self, external_id, config):
        response = self.request("GET", "/offer/v1.0/user/me/realestate/ext-" + quote(external_id, safe=""), config)
        if response.status_code == 404:
            return None
        data = checked(response)
        objects = [v for k, v in data.items() if k.startswith("realestates.") and isinstance(v, dict)]
        if len(objects) != 1 or objects[0].get("externalId") != external_id or not objects[0].get("@id"):
            raise ProtocolError("unknown", "Objektantwort passt nicht zur eingefrorenen externen Kennung.")
        return str(objects[0]["@id"])

    def reconcile_photo(self, identifier, photo, config):
        response = self.request(
            "GET",
            f"/offer/v1.0/user/me/realestate/{quote(identifier, safe='')}/attachment/?externalId={quote(photo['id'], safe='')}",
            config,
        )
        if response.status_code == 404:
            return False
        body = checked(response)
        # Exact external id/checksum pair only; do not infer from URL, title or count.
        found = []

        def visit(value):
            if isinstance(value, dict):
                if value.get("externalId") == photo["id"]:
                    found.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(body)
        return len(found) == 1 and found[0].get("externalCheckSum") == photo["sha256"]

    def reconcile_content(self, identifier, listing, config):
        response = self.request("GET", f"/offer/v1.0/user/me/realestate/{quote(identifier, safe='')}", config)
        if response.status_code == 404:
            return False
        body = checked(response).get("realestates.apartmentRent", {})
        expected = self._realestate_payload(listing)["realestates.apartmentRent"]

        def matches(expected, actual):
            if isinstance(expected, dict):
                return isinstance(actual, dict) and all(
                    k in actual and matches(v, actual[k]) for k, v in expected.items()
                )
            return expected == actual

        return matches(expected, body)

    def check_status(self, portal_listing_id, config=None):
        if not self.is_configured(config):
            return {"status": "not_configured", "portal": self.portal_name}
        channel = quote(str(config.get("publish_channel") or "10000"), safe="")
        response = self.request("GET", f"/offer/v1.0/publish/{quote(portal_listing_id, safe='')}_{channel}", config)
        if response.status_code == 404:
            return {"status": "unpublished"}
        body = checked(response)
        items = body.get("common.publishObjects", {}).get("publishObject", [])
        if isinstance(items, dict):
            items = [items]
        if not any(
            str(item.get("realEstate", {}).get("@id")) == str(portal_listing_id)
            and str(item.get("publishChannel", {}).get("@id")) == str(config.get("publish_channel") or "10000")
            for item in items
        ):
            raise ProtocolError("unknown", "IS24-Status bestätigt diese Objekt-/Kanalzuordnung nicht.")
        return {"status": "published"}

    # Legacy facade remains fail-closed: full publication requires persisted checkpoints and authorized bytes.
    def publish(self, listing_data):
        return PortalPublishResult(
            False, self.portal_name, error="Bitte die revisionsgeprüfte Portalvorschau verwenden."
        )

    def update(self, portal_listing_id, listing_data):
        return self.publish(listing_data)

    def unpublish(self, portal_listing_id):
        return self.publish({})


class OpenImmoFtpAdapter:
    portal_name = "OpenImmo"

    def __init__(self, portal_name="OpenImmo", *, ftp_factory=None):
        self.portal_name, self.ftp_factory = portal_name, ftp_factory

    def package(self, listing, photos, action, config):
        if action not in ("NEW", "CHANGE", "DELETE"):
            raise ValueError("Unbekannte OpenImmo-Aktion")
        root = ET.Element("openimmo")
        ET.SubElement(
            root,
            "uebertragung",
            {
                "art": "ONLINE",
                "umfang": "TEIL",
                "modus": "NEW",
                "version": "1.2.7",
                "sendersoftware": "ImmoManager Pro",
                "senderversion": "1",
            },
        )
        provider = ET.SubElement(root, "anbieter")

        def text(parent, key, value):
            if value is not None:
                ET.SubElement(parent, key).text = str(value)

        text(provider, "anbieternr", config["provider_number"])
        text(provider, "firma", config["company_name"])
        item = ET.SubElement(provider, "immobilie")
        category = ET.SubElement(item, "objektkategorie")
        ET.SubElement(category, "nutzungsart", {"WOHNEN": "true"})
        ET.SubElement(category, "vermarktungsart", {"MIETE_PACHT": "true"})
        ET.SubElement(ET.SubElement(category, "objektart"), "wohnung", {"wohnungtyp": "ETAGE"})
        geo = ET.SubElement(item, "geo")
        for key, source in [
            ("plz", "postcode"),
            ("ort", "city"),
            ("strasse", "street"),
            ("hausnummer", "house_number"),
        ]:
            text(geo, key, listing["address"].get(source))
        prices = ET.SubElement(item, "preise")
        text(prices, "kaltmiete", listing.get("target_rent"))
        text(prices, "nebenkosten", listing.get("service_charge"))
        ET.SubElement(prices, "waehrung", {"iso_waehrung": "EUR"})
        area = ET.SubElement(item, "flaechen")
        text(area, "wohnflaeche", listing.get("area_sqm"))
        text(area, "anzahl_zimmer", listing.get("rooms"))
        free = ET.SubElement(item, "freitexte")
        text(free, "objekttitel", listing["title"])
        text(free, "objektbeschreibung", listing.get("description"))
        attachments = ET.SubElement(item, "anhaenge")
        files = {}
        for photo, content in photos:
            if hashlib.sha256(content).hexdigest() != photo["sha256"]:
                raise ValueError("Bildhash stimmt nicht")
            name = photo["sha256"] + (".jpg" if photo["media_type"] == "image/jpeg" else ".png")
            node = ET.SubElement(attachments, "anhang", {"location": "LOCAL", "gruppe": "BILD"})
            text(node, "anhangtitel", photo["title"])
            text(node, "format", name.rsplit(".", 1)[1])
            text(ET.SubElement(node, "daten"), "pfad", name)
            files[name] = content
        technical = ET.SubElement(item, "verwaltung_techn")
        text(technical, "objektnr_intern", listing["external_id"])
        text(technical, "openimmo_obid", listing["external_id"])
        ET.SubElement(technical, "aktion", {"aktionart": action})
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(
                {"openimmo.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True), **files}.items()
            ):
                info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        return buffer.getvalue()

    def transfer(self, payload, config):
        # Certificate verification and protected data channel are mandatory.
        client = self.ftp_factory() if self.ftp_factory else FTP_TLS(context=ssl.create_default_context(), timeout=30)
        name = "immomanager-" + hashlib.sha256(payload).hexdigest() + ".zip"
        try:
            client.connect(config["ftp_host"], int(config.get("ftp_port", 21)))
            client.login(config["ftp_username"], config["ftp_password"])
            client.prot_p()
            if config.get("ftp_directory"):
                client.cwd(config["ftp_directory"])
            client.storbinary("STOR " + name, BytesIO(payload))
        except Exception:
            raise ProtocolError(
                "unknown", "FTPS-Ausgang unklar. Importbestätigung prüfen; nicht blind erneut übertragen."
            ) from None
        finally:
            client.close()
        return {
            "status": "transferred",
            "filename": name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "publication_confirmed": False,
        }


class ImmoweltAdapter(OpenImmoFtpAdapter):
    def __init__(self):
        super().__init__("Immowelt")

    def publish(self, listing_data):
        return PortalPublishResult(
            False, self.portal_name, error="Bitte die revisionsgeprüfte OpenImmo-Vorschau verwenden."
        )

    def update(self, portal_listing_id, listing_data):
        return self.publish(listing_data)

    def unpublish(self, portal_listing_id):
        return self.publish({})

    def check_status(self, portal_listing_id):
        return {"status": "not_configured", "portal": self.portal_name}


# Compatibility registry; no provider is configured implicitly.
PortalAdapter = ImmobilienScout24Adapter
_adapters: dict[str, Any] = {}


def register_adapter(adapter):
    _adapters[adapter.portal_name.lower()] = adapter


def get_adapter(name):
    return _adapters.get(name.lower())


def list_adapters():
    return [a.portal_name for a in _adapters.values()]


register_adapter(ImmobilienScout24Adapter())
register_adapter(ImmoweltAdapter())
