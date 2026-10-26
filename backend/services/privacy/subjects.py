"""Subject-specific inventory, explicit retained records, atomic portal revocation."""
import base64

from fastapi import HTTPException

from ...db import external_portal_models as portal
from ...db.data_transfer_models import ExternalReferenceORM
from ...db.e_invoice_models import EInvoiceIntakeORM, EInvoiceValidationORM
from ...db.privacy_models import PrivacyControlORM
from ..data_transfer.common import digest
from ..integrations import connection_storage as db
from ..maintenance_rows import Rows
from .resources import _plain
from .storage import key, rows


def _public(row, excluded=()):
    return {name: _plain(value) for name, value in db.values(row).items() if name not in excluded}


def extension(unit, kind, identifier):
    """No building-wide joins, auth material or another household's import rows."""
    field = "tenant_id" if kind == "tenant" else "contact_id"
    grants = rows(unit, portal.PortalGrantORM, **{field: identifier})
    identities = [db.row(unit, portal.PortalIdentityORM, key) for key in sorted({item.identity_id for item in grants})]
    links = [link for access in grants for link in rows(unit, portal.PortalCaseORM, grant_id=access.id)]
    messages = [item for link in links for item in rows(unit, portal.PortalMessageORM, case_link_id=link.id)]
    images = [image for message in messages for image in rows(unit, portal.PortalAttachmentORM, message_id=message.id)]
    contracts = {item.id for item in unit.store.list_contracts() if kind == "tenant" and item.tenant_id == identifier}
    documents = {item.id for item in unit.store.list_documents() if kind == "tenant" and (item.tenant_id == identifier or item.contract_id in contracts)}
    intakes = [item for item in rows(unit, EInvoiceIntakeORM) if item.document_id in documents]
    import_refs = [item for item in rows(unit, ExternalReferenceORM) if item.record_id == identifier and item.entity == ("tenants" if kind == "tenant" else "contacts")]
    resources = [("document", item) for item in sorted(documents)] + [("e_invoice_intake", item.id) for item in intakes]
    resources += [("portal_case", item.id) for item in links] + [("portal_identity", item.id) for item in identities]
    # Imports may contain many unrelated parties. Expose only the exact row's
    # mapping/provenance; source CSV and whole-instance exports require redaction.
    return {"portal_identities": [{"id": item.id, "email": item.email, "active": item.active} for item in identities],
        "portal_grants": [_public(item) for item in grants], "portal_cases": [_public(item) for item in links],
        "portal_messages": [_public(item, ("sender_id",)) for item in messages],
        "portal_images": [{**_public(item, ("content",)), "content_base64": base64.b64encode(item.content).decode()} for item in images],
        "portal_publications": [_public(item) for access in grants for item in rows(unit, portal.PortalPublicationORM, grant_id=access.id)],
        "e_invoice_intakes": [_public(item, ("original", "xml")) for item in intakes],
        "e_invoice_validation_runs": [_public(item) for intake in intakes for item in rows(unit, EInvoiceValidationORM, intake_id=intake.id)],
        "import_references": [_public(item) for item in import_refs],
        "privacy_controls": [_public(item) for resource_kind, resource_id in resources
            if (item := db.row(unit, PrivacyControlORM, key(resource_kind, resource_id), required=False))],
        "review_required": ["Sammelimporte und Kundenexporte können weitere Personen enthalten. Kopien dieser Dateien nur nach Inhaltsprüfung und Schwärzung fremder Daten weitergeben."],
        "resource_ids": [{"kind": resource_kind, "id": resource_id} for resource_kind, resource_id in resources]}


def inventory(unit, kind, identifier):
    from ...routers.admin import _contact_records, _tenant_records
    party = unit.store.get_tenant(identifier) if kind == "tenant" else unit.store.get_contact(identifier)
    records = (_tenant_records if kind == "tenant" else _contact_records)(identifier, source=unit.store)
    data = {"subject_kind": kind, "subject_id": identifier, "subject": party.model_dump(mode="json"),
        "records": {name: [item.model_dump(mode="json", exclude={"changes"} if name == "ownership_transfers" else None)
                           for item in items] for name, items in records.items()}, "extensions": extension(unit, kind, identifier)}
    return {"data": data, "source_sha256": digest(data), "retained_records": {name: len(items) for name, items in records.items() if items}}


def anonymize(unit, kind, identifier, patch):
    """The legacy action clears party fields and revokes related portal access in one unit."""
    from ...routers.admin import _CONTACT_PERSONAL_FIELDS, _TENANT_PERSONAL_FIELDS
    from .storage import lock_sources
    lock_sources(unit)
    source = Rows.of(unit)
    table = "tenants" if kind == "tenant" else "contacts"
    source.lock(table, identifier)
    party = source.require(table, identifier, "Partei nicht gefunden.")
    # Recompute under the write fence, including fields filled after the route's
    # preliminary read. Keep the legacy response's list of actually cleared fields.
    fields = _TENANT_PERSONAL_FIELDS if kind == "tenant" else _CONTACT_PERSONAL_FIELDS
    patch.update({name: None for name in fields if getattr(party, name) is not None})
    data = extension(unit, kind, identifier)
    if any(item["held"] for item in data["privacy_controls"]):
        raise HTTPException(409, "Verknüpfte Daten unterliegen einer Aufbewahrungssperre. Die Anonymisierung muss zunächst mit der Sperrentscheidung abgeglichen werden.")
    source.update(table, identifier, **patch)
    identities = set()
    field = "tenant_id" if kind == "tenant" else "contact_id"
    for access in rows(unit, portal.PortalGrantORM, **{field: identifier}):
        identities.add(access.identity_id)
        db.put(unit, portal.PortalGrantORM, {**db.values(access), "active": False, "revision": access.revision + 1, "updated_at": db.now()})
        for invitation in rows(unit, portal.PortalInvitationORM, grant_id=access.id):
            db.put(unit, portal.PortalInvitationORM, {**db.values(invitation), "revoked_at": db.now()})
    for identity_id in identities:
        identity = db.row(unit, portal.PortalIdentityORM, identity_id)
        other_access = any(item.active for item in rows(unit, portal.PortalGrantORM, identity_id=identity_id))
        values = {**db.values(identity), "revision": identity.revision + 1, "updated_at": db.now()}
        if not other_access:
            values.update(active=False, password_hash=None, email="erased-" + identity_id + "@invalid.example")
        db.put(unit, portal.PortalIdentityORM, values)
        for session in rows(unit, portal.PortalSessionORM, identity_id=identity_id):
            db.put(unit, portal.PortalSessionORM, {**db.values(session), "revoked_at": db.now()})
    return {"revoked_grants": len(data["portal_grants"]), "retained_messages": len(data["portal_messages"]),
        "retained_images": len(data["portal_images"]), "retained_originals": len(data["e_invoice_intakes"]),
        "notice": "Interne Akten, Originale und externe Kommunikation bleiben getrennte, weiter zu prüfende Datenbestände; dies ist keine vollständige Löschung aller personenbezogenen Daten."}
