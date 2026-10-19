"""Local listing -> expose -> lead -> viewing -> confirmed existing contract.

Uses the current leads, viewing_appointments and contracts; never creates rent
bookings, payment allocations or a parallel contract ledger.
"""

from datetime import datetime
from io import BytesIO
from uuid import uuid4
from xml.sax.saxutils import escape

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .. import models
from ..db.orm_models import LeadORM, ViewingAppointmentORM
from . import channel_workflows as flow
from .integrations import connection_storage as db
from .reletting import open_project_id
from .workspace_contexts import resolve_context, same_revision


class MarketingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: str
    parameters: dict = Field(default_factory=dict)


def _put(unit, orm, collection, record):
    if unit.db is None:
        unit.insert(getattr(unit.store, collection), record.id, record)
    else:
        values = record.model_dump()
        for key, value in values.items():
            if isinstance(value, datetime):
                values[key] = value.replace(tzinfo=None)
        existing = unit.db.get(orm, record.id)
        if existing is None:
            unit.db.add(orm(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        unit.db.flush()


def action(store, actor, listing_id, payload):
    with flow.work(store, actor, "/listings") as unit:
        ctx = resolve_context(unit.store, "listing", listing_id, actor, lock=True)
        prior = flow.commands.replay(unit, actor, "marketing:" + listing_id, payload)
        if prior:
            return prior
        frozen, assets = flow.freeze(unit, "is24", listing_id)
        if db.digest(frozen) != payload.source_sha256:
            raise HTTPException(409, "Inserat oder Bilder verändert. Vorschau neu laden.")
        listing = unit.store.get_listing(listing_id)
        apartment = unit.store.get_unit(listing.unit_id)
        params = payload.parameters
        if payload.action == "lead":
            name = str(params.get("full_name", "")).strip()
            if not name:
                raise HTTPException(422, "Name des Interessenten fehlt.")
            record: models.Lead | models.ViewingAppointment = models.Lead(
                id=str(uuid4()),
                **models.LeadCreate(
                    listing_id=listing_id,
                    unit_id=listing.unit_id,
                    full_name=name,
                    email=params.get("email") or None,
                    phone=params.get("phone") or None,
                    source="Lokales Exposé",
                    project_id=open_project_id(unit.store, listing.unit_id),
                ).model_dump(),
            )
            _put(unit, LeadORM, "leads", record)
            result = {"lead": record.model_dump(mode="json")}
        elif payload.action in ("viewing", "complete_viewing", "confirm_contract"):
            lead_ctx = resolve_context(unit.store, "lead", str(params.get("lead_id", "")), actor, lock=True)
            lead = unit.store.get_lead(lead_ctx["entity_id"])
            if lead.listing_id != listing_id or lead.unit_id != listing.unit_id:
                raise HTTPException(409, "Interessent gehört nicht zu diesem Inserat.")
            if not same_revision(lead_ctx["revision"], str(params.get("lead_revision", ""))):
                raise HTTPException(409, "Interessent verändert. Neu laden.")
            if payload.action == "viewing":
                try:
                    when = datetime.fromisoformat(params["scheduled_at"])
                except (KeyError, ValueError, TypeError):
                    raise HTTPException(422, "Besichtigungszeitpunkt mit Zeitzone angeben.") from None
                if when.tzinfo is None:
                    raise HTTPException(422, "Besichtigungszeitpunkt benötigt eine Zeitzone.")
                record = models.ViewingAppointment(
                    id=str(uuid4()),
                    **models.ViewingAppointmentCreate(
                        lead_id=lead.id, unit_id=listing.unit_id, scheduled_at=when
                    ).model_dump(),
                )
                _put(unit, ViewingAppointmentORM, "viewing_appointments", record)
                result = {"viewing": record.model_dump(mode="json")}
            else:
                viewing_ctx = resolve_context(
                    unit.store, "viewing", str(params.get("viewing_id", "")), actor, lock=True
                )
                viewing = unit.store.get_viewing_appointment(viewing_ctx["entity_id"])
                if viewing.lead_id != lead.id or viewing.unit_id != listing.unit_id:
                    raise HTTPException(409, "Besichtigung gehört nicht zu diesem Interessenten.")
                if not same_revision(viewing_ctx["revision"], str(params.get("viewing_revision", ""))):
                    raise HTTPException(409, "Besichtigung verändert. Neu laden.")
                if payload.action == "complete_viewing":
                    if params.get("completed_confirmed") is not True:
                        raise HTTPException(422, "Tatsächliche Besichtigung bestätigen.")
                    record = viewing.model_copy(update={"status": "completed", "updated_at": db.now()})
                    _put(unit, ViewingAppointmentORM, "viewing_appointments", record)
                    result = {"viewing": record.model_dump(mode="json")}
                else:
                    if viewing.status != "completed" or params.get("contract_confirmed") is not True:
                        raise HTTPException(
                            409, "Besichtigung abschließen und tatsächlichen Vertragsabschluss bestätigen."
                        )
                    contract_ctx = resolve_context(
                        unit.store, "contract", str(params.get("contract_id", "")), actor, lock=True
                    )
                    contract = unit.store.get_contract(contract_ctx["entity_id"])
                    if (
                        contract.unit_id != listing.unit_id
                        or contract.property_id != apartment.property_id
                        or contract.status != "active"
                    ):
                        raise HTTPException(409, "Vertrag gehört nicht zur angebotenen Einheit oder ist nicht gültig.")
                    if not same_revision(contract_ctx["revision"], str(params.get("contract_revision", ""))):
                        raise HTTPException(409, "Vertrag verändert. Neu laden.")
                    # Identity is explicitly chosen, never inferred from a matching name.
                    tenant_ctx = resolve_context(unit.store, "tenant", contract.tenant_id, actor)
                    if params.get("tenant_id") != tenant_ctx["entity_id"]:
                        raise HTTPException(409, "Gewählte Vertragspartei ausdrücklich bestätigen.")
                    # Durable immutable command receipt connects the original listing revision
                    # and independently reviewed current lead/viewing/contract identities.
                    result = {
                        "confirmed_contract": {
                            "listing_id": listing_id,
                            "lead_id": lead.id,
                            "viewing_id": viewing.id,
                            "contract_id": contract.id,
                            "tenant_id": contract.tenant_id,
                            "confirmed_by": actor,
                            "confirmed_at": db.stamp(db.now()),
                            "source_sha256": payload.source_sha256,
                            "lead_revision": lead_ctx["revision"],
                            "viewing_revision": viewing_ctx["revision"],
                            "contract_revision": contract_ctx["revision"],
                        }
                    }
        else:
            raise HTTPException(422, "Unbekannte Vermarktungsaktion.")
        flow.commands.save_command(unit, actor, "marketing:" + listing_id, payload, ctx, result)
        return result


def overview(store, actor, listing_id):
    with flow.work(store, actor) as unit:
        resolve_context(unit.store, "listing", listing_id, actor)
        listing = unit.store.get_listing(listing_id)
        leads = [item.model_dump(mode="json") for item in unit.store.list_leads() if item.listing_id == listing_id]
        lead_ids = {item["id"] for item in leads}
        viewings = [
            item.model_dump(mode="json") for item in unit.store.list_viewing_appointments() if item.lead_id in lead_ids
        ]
        contracts = [
            item.model_dump(mode="json") for item in unit.store.list_contracts() if item.unit_id == listing.unit_id
        ]
        from sqlalchemy import select

        from ..db.business_qol_models import BusinessCommandORM

        records = (
            list(
                unit.db.scalars(
                    select(BusinessCommandORM).filter_by(operation="marketing:" + listing_id, entity_id=listing_id)
                )
            )
            if unit.db
            else [
                item
                for item in unit.store.business_qol_commands.values()
                if item.operation == "marketing:" + listing_id and item.entity_id == listing_id
            ]
        )
        confirmations = [
            item.response["confirmed_contract"] for item in records if "confirmed_contract" in item.response
        ]
        return {"leads": leads, "viewings": viewings, "contracts": contracts, "confirmations": confirmations}


def expose(store, actor, listing_id, source_sha256):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    with flow.work(store, actor) as unit:
        frozen, assets = flow.freeze(unit, "is24", listing_id)
        if db.digest(frozen) != source_sha256:
            raise HTTPException(409, "Exposéquelle verändert. Vorschau neu laden.")
        listing = frozen["listing"]
        buffer = BytesIO()
        styles = getSampleStyleSheet()
        story = [Paragraph(escape(listing["title"]), styles["Title"])]
        address = listing["address"]
        for text in (
            f"{address['street']} {address['house_number']}, {address['postcode']} {address['city']}",
            f"Kaltmiete: {listing['target_rent']} EUR · Wohnfläche: {listing['area_sqm']} m² · Zimmer: {listing['rooms']}",
            listing.get("description") or "",
            "Quellnachweis: " + source_sha256,
        ):
            story.extend([Paragraph(escape(text).replace("\n", "<br/>"), styles["BodyText"]), Spacer(1, 12)])
        for info, content in assets:
            try:
                image = ImageReader(BytesIO(content))
                width, height = image.getSize()
                ratio = min(440 / width, 300 / height, 1)
                story.extend(
                    [
                        Paragraph(escape(info["title"]), styles["Heading2"]),
                        Image(BytesIO(content), width=width * ratio, height=height * ratio),
                    ]
                )
            except Exception:
                raise HTTPException(
                    422, "Ein Originalbild ist nicht lesbar. Bild vor Exposéerstellung korrigieren."
                ) from None
        SimpleDocTemplate(buffer, title=listing["title"]).build(story)
        return buffer.getvalue()
