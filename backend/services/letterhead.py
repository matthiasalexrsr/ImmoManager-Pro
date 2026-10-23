"""Briefkopf: sender, contact, bank details, footer and logo shared by every letter.

The text fields are business defaults of the settings catalogue (installation,
per object, personal): `document_sender`, `document_address`, `document_signature`,
`document_contact`, `document_bank`, `document_footer`. The logo is a setting rule
of its own (`document_logo`, installation or object scope) so the catalogue never
ships the picture. A letter freezes `source()` in its review (texts and the logo's
SHA-256) and embeds `logo_bytes()`; a letterhead changed after the preview makes
the publication fail with 412, archived originals never change.
"""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from ..db.daily_models import SettingRuleORM
from ..domain.clock import local_today
from . import daily_state as state
from . import document_versions as archive
from . import workspace_contexts as contexts
from .portfolio_scope import scope_context, scope_from_user
from .settings_catalogue import effective, record_audit, rule

TEXT_FIELDS = {"sender_name": "document_sender", "sender_address": "document_address",
               "signature": "document_signature", "contact": "document_contact",
               "bank": "document_bank", "footer": "document_footer"}
LOGO_KEY = "document_logo"
MAX_UPLOAD_BYTES = 1024 * 1024
MAX_STORED_BYTES = 1024 * 1024
MAX_WIDTH = 1200
MAX_PIXELS = 40_000_000
WRITE_AREA = "/letterhead"


def normalize_logo(raw: bytes) -> tuple[bytes, int, int]:
    """An uploaded PNG or JPEG as upright PNG without metadata, at most MAX_WIDTH pixels wide."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not raw:
        raise HTTPException(422, "Bitte eine Bilddatei für das Logo auswählen.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Das Logo darf höchstens 1 MB groß sein.")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in ("PNG", "JPEG"):
                raise HTTPException(415, "Das Logo muss eine PNG- oder JPEG-Datei sein.")
            width, height = source.size
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise HTTPException(422, "Das Logo ist zu groß. Bitte eine kleinere Bilddatei wählen.")
            picture = ImageOps.exif_transpose(source)
            transparent = picture.mode in ("RGBA", "LA", "PA") or (picture.mode == "P" and "transparency" in picture.info)
            picture = picture.convert("RGBA" if transparent else "RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(415, "Die Datei ist kein lesbares Bild (PNG oder JPEG).") from None
    if picture.width > MAX_WIDTH:
        picture = picture.resize((MAX_WIDTH, max(1, round(picture.height * MAX_WIDTH / picture.width))),
                                 Image.Resampling.LANCZOS)
    output = BytesIO()
    picture.save(output, format="PNG", optimize=False)
    content = output.getvalue()
    if len(content) > MAX_STORED_BYTES:
        raise HTTPException(413, "Das Logo ist nach der Umwandlung größer als 1 MB. Bitte ein kleineres Bild wählen.")
    return content, picture.width, picture.height


def _check_scope(unit, scope: str, *, lock: bool = False) -> None:
    if scope == "global":
        if not scope_from_user(unit.user).unrestricted:
            raise HTTPException(403, "Der installationsweite Briefkopf benötigt Zugriff auf alle Bestände.")
        return
    if not scope.startswith("object:") or not scope[7:]:
        raise HTTPException(422, "Geltungsbereich „global“ oder „object:<Objekt>“ angeben.")
    contexts.resolve_context(unit.store, "property", scope[7:], unit.actor_id, lock=lock)


def _logo_meta(payload: dict) -> dict | None:
    value = payload.get("value")
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in ("sha256", "width", "height", "size_bytes", "filename")}


def _logo(unit, property_id: str | None) -> tuple[dict | None, str]:
    """The effective logo rule (object before installation) and its scope."""
    for scope in (("object:" + property_id) if property_id else None, "global"):
        if scope:
            payload = rule(unit, scope, LOGO_KEY)["payload"]
            if isinstance(payload.get("value"), dict):
                return payload["value"], scope
    return None, "Standard"


def logo_bytes(unit, property_id: str | None) -> bytes | None:
    value, _ = _logo(unit, property_id)
    if value is None:
        return None
    content = base64.b64decode(value["data"])
    if hashlib.sha256(content).hexdigest() != value["sha256"]:
        raise HTTPException(503, "Das gespeicherte Logo ist beschädigt. Bitte im Briefkopf neu hochladen.")
    return content


def source(unit, property_id: str | None, *, fallback_sender: str = "") -> dict[str, Any]:
    """The letterhead a letter freezes in its review: texts and the logo's checksum."""
    values = {name: (effective(unit, key, property_id)[0] or "").strip() for name, key in TEXT_FIELDS.items()}
    values["sender_name"] = values["sender_name"] or fallback_sender.strip()
    logo, _ = _logo(unit, property_id)
    values["logo"] = None if logo is None else {key: logo[key] for key in ("sha256", "width", "height")}
    return values


def view(store, actor_id: str, property_id: str | None = None) -> dict[str, Any]:
    """The effective letterhead with the origin of each field and the logo rules one may change."""
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        if property_id:
            contexts.resolve_context(unit.store, "property", property_id, actor_id)
        fields = {}
        for name, key in TEXT_FIELDS.items():
            value, origin = effective(unit, key, property_id)
            fields[name] = {"key": key, "value": value, "origin": origin}
        logo, origin = _logo(unit, property_id)
        admin = unit.user["role"] in ("eigentuemer", "verwalter")
        scopes = []
        if admin and scope_from_user(unit.user).unrestricted:
            scopes.append("global")
        if admin and property_id:
            scopes.append("object:" + property_id)
        rules = {}
        for scope in scopes:
            saved = rule(unit, scope, LOGO_KEY)
            rules[scope] = {"revision": saved["revision"], "logo": _logo_meta(saved["payload"])}
        return {"property_id": property_id, "fields": fields,
                "logo": None if logo is None else {**{key: logo[key] for key in ("sha256", "width", "height", "size_bytes", "filename")},
                                                   "origin": origin},
                "logo_rules": rules, "can_edit": bool(scopes)}


def logo_png(store, actor_id: str, scope: str) -> bytes:
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        if scope != "global":
            _check_scope(unit, scope)
        value = rule(unit, scope, LOGO_KEY)["payload"].get("value")
        if not isinstance(value, dict):
            raise HTTPException(404, "Für diesen Geltungsbereich ist kein Logo hinterlegt.")
        content = base64.b64decode(value["data"])
        if hashlib.sha256(content).hexdigest() != value["sha256"]:
            raise HTTPException(503, "Das gespeicherte Logo ist beschädigt. Bitte im Briefkopf neu hochladen.")
        return content


def _write(unit, scope: str, payload: dict, base_revision: int) -> dict:
    before = rule(unit, scope, LOGO_KEY)
    if before["revision"] != base_revision:
        raise HTTPException(409, "Das Logo wurde zwischenzeitlich geändert. Bitte neu laden.")
    result = {"revision": base_revision + 1, "payload": payload}
    if unit.db is None:
        unit.insert(state.memory(unit, "rules"), (scope, LOGO_KEY), result)
    else:
        row = unit.db.scalar(select(SettingRuleORM).where(SettingRuleORM.scope == scope,
                                                          SettingRuleORM.key == LOGO_KEY).with_for_update())
        if row is None:
            row = SettingRuleORM(scope=scope, key=LOGO_KEY)
            unit.db.add(row)
        row.revision, row.payload, row.updated_at = result["revision"], payload, state.now()
        unit.db.flush()
    return {"before": {"revision": before["revision"], "logo": _logo_meta(before["payload"])},
            "after": {"revision": result["revision"], "logo": _logo_meta(payload)}}


def _command(store, actor_id: str, scope: str, base_revision: int, idempotency_key: str, operation: str,
             payload: dict | None, fingerprint_body: dict) -> dict:
    if type(base_revision) is not int or base_revision < 0:
        raise HTTPException(422, "Erwartete Revision fehlt.")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 120:
        raise HTTPException(422, "Ungültige Vorgangskennung.")
    with archive.work(store, actor_id, write_areas=(WRITE_AREA,)) as unit, contexts.bound_actor(unit.user), \
            scope_context(scope_from_user(unit.user)):
        if unit.user["role"] not in ("eigentuemer", "verwalter"):
            raise HTTPException(403, "Der Briefkopf benötigt Verwaltungsrechte.")
        _check_scope(unit, scope, lock=True)
        fingerprint = state.digest(operation, {"scope": scope, "base_revision": base_revision, **fingerprint_body})
        saved = state.replay(unit, idempotency_key, fingerprint)
        if saved is not None:
            return saved
        change = _write(unit, scope, payload or {}, base_revision)
        record_audit(unit, idempotency_key, "settings_change", scope,
                     {LOGO_KEY: change["before"]}, {LOGO_KEY: change["after"]})
        response = {"scope": scope, **change["after"]}
        state.remember(unit, idempotency_key, fingerprint, response)
        return response


def put_logo(store, actor_id: str, scope: str, raw: bytes, filename: str | None, base_revision: int,
             idempotency_key: str) -> dict:
    content, width, height = normalize_logo(raw)
    checksum = hashlib.sha256(content).hexdigest()
    name = "".join(char for char in (filename or "logo.png") if char.isprintable())[:120] or "logo.png"
    payload = {"value": {"data": base64.b64encode(content).decode("ascii"), "sha256": checksum, "width": width,
                         "height": height, "size_bytes": len(content), "filename": name, "media_type": "image/png"}}
    return _command(store, actor_id, scope, base_revision, idempotency_key, "letterhead_logo_put", payload,
                    {"sha256": checksum, "filename": name})


def delete_logo(store, actor_id: str, scope: str, base_revision: int, idempotency_key: str) -> dict:
    return _command(store, actor_id, scope, base_revision, idempotency_key, "letterhead_logo_delete", {}, {})


def sample_pdf(store, actor_id: str, property_id: str | None = None) -> bytes:
    """A specimen letter with the effective letterhead, to check layout, logo and footer."""

    from .letter_layout import render_letter
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        if property_id:
            contexts.resolve_context(unit.store, "property", property_id, actor_id)
        head = source(unit, property_id, fallback_sender="Ihr Name oder Ihre Verwaltung")
        letter = {
            "recipient_name": "Erika Mustermann", "recipient_address": "Musterstraße 1\n12345 Musterstadt",
            "issue_date": local_today().isoformat(), "subject": "Musterbrief: so sehen Ihre Briefe aus",
            "info": [["Vertrag", "MV-0001"], ["Objekt", "Musterhaus, Whg. 1"]],
            "salutation": "Sehr geehrte Frau Mustermann,",
            "body": ("dieser Musterbrief zeigt den Briefkopf, wie er auf allen Schreiben erscheint: Absender und Logo "
                     "oben, die Anschrift im Fenster eines Briefumschlags (DIN 5008, Form B) und Kontakt sowie "
                     "Bankverbindung in der Fußzeile.\n\nÄnderungen am Briefkopf gelten für alle neuen Briefe. "
                     "Bereits archivierte Briefe bleiben unverändert."),
            "closing": "Mit freundlichen Grüßen", "signature": head["signature"] or head["sender_name"],
        }
        return render_letter(letter, head, logo_bytes(unit, property_id), draft=True, draft_label="MUSTER")
