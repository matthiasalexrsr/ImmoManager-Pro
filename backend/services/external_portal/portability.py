"""Only business relationships and communications travel in a customer export."""
from ...db.external_portal_models import (
    PortalAttachmentORM,
    PortalCaseORM,
    PortalEventORM,
    PortalGrantORM,
    PortalIdentityORM,
    PortalMessageORM,
    PortalPublicationORM,
)

# Parent-before-child order. Sessions, invitations, attempts and command receipts
# are operating credentials, not customer migration data.
MODELS = (PortalIdentityORM, PortalGrantORM, PortalPublicationORM, PortalCaseORM,
          PortalMessageORM, PortalAttachmentORM, PortalEventORM)


def sanitized(model, payload):
    if model is PortalIdentityORM:
        return {**payload, "password_hash": None, "active": False}
    return payload


def restored(model, value):
    if model in (PortalIdentityORM, PortalGrantORM, PortalPublicationORM, PortalCaseORM):
        value = {**value, "active": False, "revision": value["revision"] + 1}
    if model is PortalIdentityORM:
        value["password_hash"] = None
    return value


def validate(records, business, versions):
    """Typed, resolved business references; no imported credential can log in."""
    by_table = {model.__tablename__: {value["id"]: value for candidate, value in records if candidate is model} for model in MODELS}
    for model, value in records:
        for column in model.__table__.columns:
            for fk in column.foreign_keys:
                identifier = value[column.name]
                target = fk.column.table.name
                known = by_table.get(target, versions if target == "document_versions" else business.get(target, {}))
                if identifier is not None and identifier not in known:
                    raise ValueError("Portalnachweis verweist auf fehlende Daten: " + target)
        if model is PortalIdentityORM and (value["password_hash"] is not None or value["active"]):
            raise ValueError("Ein Kundenexport darf keine aktiven Portal-Zugangsdaten enthalten.")
        if model is PortalGrantORM:
            if value["kind"] not in ("tenant", "owner"):
                raise ValueError("Unbekannte Portalart.")
            expected = {"kind": value["kind"], "party_id": value["tenant_id"] or value["contact_id"],
                "relation_id": value["contract_id"] or value["ownership_id"], "portfolio_id": value["portfolio_id"]}
            if any(value["binding"].get(key) != item for key, item in expected.items()):
                raise ValueError("Widersprüchliche Portalbindung.")
            if value["binding"].get("property_id") not in business.get("properties", {}):
                raise ValueError("Portalimmobilie fehlt.")
        if model is PortalPublicationORM and value["sha256"] != versions[value["version_id"]]["sha256"]:
            raise ValueError("Die veröffentlichte Portalversion stimmt nicht mit dem Original überein.")
        if model is PortalAttachmentORM:
            import hashlib
            if value["media_type"] != "image/jpeg" or not value["content"].startswith(b"\xff\xd8\xff") or hashlib.sha256(value["content"]).hexdigest() != value["sha256"]:
                raise ValueError("Ungültiges Portalbild.")
        if model is PortalMessageORM and value["sender_kind"] not in ("internal", "external"):
            raise ValueError("Ungültige Nachrichtenherkunft.")
