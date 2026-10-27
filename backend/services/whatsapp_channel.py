"""Narrow WhatsApp Cloud API transport hooks for the shared outbox.

Only template messages and JPEG/PNG/PDF media are supported. No direct-text
session policy is guessed. No credentials/configuration are loaded here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

import httpx

from .portal_adapter import ProtocolError, checked

MEDIA = {
    "image/jpeg": (5 * 1024 * 1024, b"\xff\xd8\xff"),
    "image/png": (5 * 1024 * 1024, b"\x89PNG\r\n\x1a\n"),
    "application/pdf": (100 * 1024 * 1024, b"%PDF-"),
}


def validate_media(content, media_type):
    if media_type not in MEDIA:
        raise ValueError("Unterstützt werden JPEG, PNG und PDF.")
    maximum, magic = MEDIA[media_type]
    if not content.startswith(magic) or len(content) > maximum:
        raise ValueError("Dateiinhalt oder Dateigröße passt nicht zum Medientyp.")


def template_request(payload):
    if payload.get("opt_in") is not True or not str(payload.get("opt_in_evidence") or "").strip():
        raise ValueError("Eine belegte WhatsApp-Einwilligung ist erforderlich.")
    recipient = str(payload.get("to", "")).removeprefix("+")
    if not re.fullmatch(r"[1-9][0-9]{7,14}", recipient):
        raise ValueError("Internationale Empfängernummer angeben.")
    name, language = payload.get("template_name", ""), payload.get("language_code", "")
    if not isinstance(name, str) or not isinstance(language, str):
        raise ValueError("Template-Name und Sprache müssen Text sein.")
    if not re.fullmatch(r"[a-z0-9_]{1,512}", name):
        raise ValueError("Freigegebenen Template-Namen angeben.")
    if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", language):
        raise ValueError("Template-Sprache angeben, etwa de oder de_DE.")
    components = payload.get("components", [])
    if not isinstance(components, list):
        raise ValueError("Template-Parameter müssen eine Liste sein.")
    for component in components:
        if not isinstance(component, dict) or component.get("type") not in ("body", "header", "button"):
            raise ValueError("Nicht unterstützte Template-Komponente.")
        allowed = {"type", "parameters"} | ({"sub_type", "index"} if component["type"] == "button" else set())
        if set(component) - allowed:
            raise ValueError("Unbekanntes Template-Feld.")
        if component["type"] == "button" and (
            component.get("sub_type") not in ("quick_reply", "url")
            or not re.fullmatch(r"[0-9]", str(component.get("index", "")))
        ):
            raise ValueError("Button-Typ und Index prüfen.")
        if not isinstance(component.get("parameters", []), list):
            raise ValueError("Template-Parameter müssen eine Liste sein.")
        for parameter in component.get("parameters", []):
            if not isinstance(parameter, dict):
                raise ValueError("Ungültiger Template-Parameter.")
            kind = parameter.get("type")
            if (
                kind == "text"
                and set(parameter) == {"type", "text"}
                and isinstance(parameter["text"], str)
                and 0 < len(parameter["text"]) <= 32768
            ):
                continue
            if (
                kind == "payload"
                and set(parameter) == {"type", "payload"}
                and isinstance(parameter["payload"], str)
                and 0 < len(parameter["payload"]) <= 128
            ):
                continue
            if kind in ("image", "document") and set(parameter) == {"type", kind}:
                media = parameter[kind]
                if isinstance(media, dict) and set(media) == {"id"} and re.fullmatch(r"[0-9]{1,64}", str(media["id"])):
                    continue
            raise ValueError("Unterstützt werden Text-, Button- und hochgeladene Bild-/PDF-Parameter.")
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "template",
        "template": {"name": name, "language": {"code": language}, "components": components},
    }
    if payload.get("correlation"):
        body["biz_opaque_callback_data"] = str(payload["correlation"])
    return body


class WhatsAppAdapter:
    def __init__(self, client=None):
        self.client = client

    def request(self, method, path, config, **kwargs):
        version = str(config.get("graph_version", ""))
        if (
            not re.fullmatch(r"v[0-9]+\.0", version)
            or not re.fullmatch(r"[0-9]{1,32}", str(config.get("phone_number_id", "")))
            or not config.get("api_token")
        ):
            raise ProtocolError("failed", "Graph-Version, Telefonnummer-ID und API-Token fehlen oder sind ungültig.")
        try:
            return (self.client.request if self.client else httpx.request)(
                method,
                "https://graph.facebook.com/" + version + "/" + path,
                headers={"Authorization": "Bearer " + config["api_token"]},
                timeout=30,
                follow_redirects=False,
                **kwargs,
            )
        except httpx.HTTPError:
            raise ProtocolError(
                "unknown" if method == "POST" else "failed",
                "WhatsApp-Antwort fehlt. Keine automatische Sendewiederholung.",
            ) from None

    def send(self, payload, config):
        body = template_request(payload)
        result = checked(
            self.request("POST", str(config["phone_number_id"]) + "/messages", config, json=body), write=True
        )
        messages = result.get("messages", [])
        if len(messages) != 1 or not messages[0].get("id"):
            raise ProtocolError("unknown", "Keine eindeutige WhatsApp-Nachrichtenkennung bestätigt.")
        return {"status": "accepted", "external_id": messages[0]["id"], "delivery_confirmed": False}

    def upload(self, content, name, media_type, config):
        validate_media(content, media_type)
        body = checked(
            self.request(
                "POST",
                str(config["phone_number_id"]) + "/media",
                config,
                data={"messaging_product": "whatsapp", "type": media_type},
                files={"file": (name, content, media_type)},
            ),
            write=True,
        )
        if not re.fullmatch(r"[0-9]{1,64}", str(body.get("id", ""))):
            raise ProtocolError("unknown", "Medienkennung fehlt.")
        return {"id": body["id"], "sha256": hashlib.sha256(content).hexdigest(), "media_type": media_type}

    def receive_media(self, identifier, config):
        if not re.fullmatch(r"[0-9]{1,64}", identifier):
            raise ValueError("Ungültige Medienkennung.")
        metadata = checked(self.request("GET", identifier, config))
        url = urlsplit(metadata.get("url", ""))
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.port not in (None, 443)
            or not (url.hostname == "lookaside.fbsbx.com" or (url.hostname or "").endswith(".fbsbx.com"))
        ):
            raise ProtocolError("failed", "Nicht freigegebene Medienadresse.")
        try:
            # Streaming bounds memory even if Content-Length is missing or forged.
            client = self.client or httpx.Client(timeout=30, follow_redirects=False)
            try:
                with client.stream(
                    "GET",
                    url.geturl(),
                    headers={"Authorization": "Bearer " + config["api_token"]},
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise ProtocolError("failed", "Medienabruf abgelehnt.")
                    content = bytearray()
                    maximum = MEDIA.get(metadata.get("mime_type"), (0, b""))[0]
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > maximum:
                            raise ProtocolError("failed", "Mediengröße überschritten.")
            finally:
                if not self.client:
                    client.close()
        except httpx.HTTPError:
            raise ProtocolError("failed", "Medienabruf fehlgeschlagen.") from None
        data = bytes(content)
        validate_media(data, metadata["mime_type"])
        if hashlib.sha256(data).hexdigest() != metadata.get("sha256"):
            raise ProtocolError("failed", "Empfangene Medien stimmen nicht mit dem Anbieterhash überein.")
        return data, metadata


def challenge(mode, token, value, expected):
    if mode != "subscribe" or not expected or not hmac.compare_digest((token or "").encode(), expected.encode()):
        raise ProtocolError("failed", "Webhook-Verifikation abgelehnt.", 403)
    return value


def webhook(raw, signature, secret, phone_number_id):
    if (
        not secret
        or not isinstance(signature, str)
        or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature)
        or not hmac.compare_digest(signature, "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest())
    ):
        raise ProtocolError("failed", "Webhook-Signatur ungültig.", 403)
    try:
        body = json.loads(raw)
        if body.get("object") != "whatsapp_business_account":
            raise ValueError()
        events = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change["value"]
                if change.get("field") != "messages" or str(value["metadata"]["phone_number_id"]) != str(
                    phone_number_id
                ):
                    raise ValueError()
                for status in value.get("statuses", []):
                    if status["status"] not in ("sent", "delivered", "read", "failed"):
                        raise ValueError()
                    events.append(
                        {
                            "kind": "status",
                            "external_id": status["id"],
                            "status": status["status"],
                            "recipient": status["recipient_id"],
                            "timestamp": status["timestamp"],
                            "correlation": status.get("biz_opaque_callback_data"),
                            "errors": status.get("errors", []),
                        }
                    )
                for message in value.get("messages", []):
                    events.append(
                        {
                            "kind": "message",
                            "external_id": message["id"],
                            "sender": message["from"],
                            "reply_to": message.get("context", {}).get("id"),
                            "timestamp": message["timestamp"],
                            "original": message,
                        }
                    )
        return events
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProtocolError("failed", "Webhook-Inhalt ungültig.", 422) from None


def advance_status(current, incoming):
    # Preserve a late failure as an event, without rolling back proven delivery/read.
    rank = {"unknown": -1, "accepted": 0, "sent": 1, "failed": 1.5, "delivered": 2, "read": 3}
    return incoming if rank.get(incoming, -2) > rank.get(current, -1) else current
