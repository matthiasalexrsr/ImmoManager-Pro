"""Re-letting a unit as a project (Neuvermietung).

The steps of the office in one place: prepare the offer (rent, charges, deposit, the
requirements, the texts and the energy certificate's figures an advertisement has to
state), download the exposé and copy the portal texts, record applicants, book viewings
(they appear in the viewing calendar) and note the impression afterwards, compare the
applicants by the same parameters, take the chosen one over as tenant (the contract form
opens prefilled) and delete the other applicants' data once they are no longer needed.

Nothing leaves the app: the exposé is a PDF to download, the portal texts are for copy and
paste, a listing created from the project is transferred to a portal only by its own
explicit command, and the AI comparison is a pseudonymised question the person sends in
the assistant. The comparison states facts against the project's requirements; it does
not rank by a hidden score.

All database work runs in document_versions.work() units (one SQL transaction, or memory
with undo) called from synchronous endpoints in the thread pool. Writes re-check the
actor's rights under the account lock up to the commit; reads follow the portfolio
boundary of the unit (a foreign project is "not found").
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select

from ..db.business_qol_models import BusinessCommandORM, ConversationNoteORM
from ..db.orm_models import (
    ChangeHistoryORM,
    LeadAttachmentORM,
    LeadORM,
    ListingORM,
    RelettingProjectORM,
    TenantORM,
    UnitORM,
    ViewingAppointmentORM,
)
from ..domain.clock import local_today
from ..models import Lead, Listing, Tenant, Unit, ViewingAppointment
from ..models_reletting import (
    AcceptRequest,
    ApplicantInput,
    CloseRequest,
    LeadAttachment,
    PurgeRequest,
    RejectRequest,
    RelettingProject,
    RelettingStart,
    RelettingUpdate,
    ViewingInput,
)
from ..storage import NotFoundError
from . import document_versions as archive
from .notifier import day, eur

EDIT_AREAS = ("/reletting",)
_ORM: dict[str, Any] = {
    "reletting_projects": RelettingProjectORM, "leads": LeadORM, "viewing_appointments": ViewingAppointmentORM,
    "lead_attachments": LeadAttachmentORM, "tenants": TenantORM, "units": UnitORM, "listings": ListingORM,
}
_MODELS: dict[str, Any] = {
    "reletting_projects": RelettingProject, "leads": Lead, "viewing_appointments": ViewingAppointment,
    "lead_attachments": LeadAttachment,
}
DECIDED = ("accepted", "rejected", "withdrawn")
CLOSED_OUT = ("rejected", "withdrawn")
# a rejected applicant may claim discrimination within two months (§ 21 Abs. 5 AGG); after that
# their data is no longer needed. Past this many days the overview recommends deleting it.
PURGE_AFTER_DAYS = 90
UPCOMING_DAYS = 120
DOCUMENTS = (("doc_self_disclosure", "Selbstauskunft"), ("doc_income", "Einkommensnachweis"),
             ("doc_credit_report", "Bonitätsauskunft"), ("doc_landlord_reference", "Vermieterbescheinigung"),
             ("doc_id_checked", "Ausweisprüfung"))
EMPLOYMENT = {"permanent": "unbefristet angestellt", "temporary": "befristet angestellt",
              "self_employed": "selbstständig", "retired": "in Rente / Pension", "student": "in Ausbildung / Studium",
              "other": "sonstiges"}
PETS = {"allowed": "erlaubt", "on_request": "nach Absprache", "not_allowed": "nicht erlaubt"}
CERTIFICATES = {"consumption": "Verbrauchsausweis", "demand": "Bedarfsausweis", "none": "kein Energieausweis"}
_NO_PETS = {"", "-", "—", "keine", "kein", "nein", "no", "none", "0"}
KINDS = {"wohnung": "Wohnung", "apartment": "Wohnung", "flat": "Wohnung", "gewerbe": "Gewerbefläche",
         "commercial": "Gewerbefläche", "stellplatz": "Stellplatz", "parking": "Stellplatz", "garage": "Garage",
         "keller": "Kellerraum"}


def now() -> datetime:
    # aware like the store's other records; the SQL path stores naive UTC (_put)
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


def _not_found(what: str = "Neuvermietungsprojekt") -> HTTPException:
    return HTTPException(404, f"{what} nicht vorhanden.")


def _conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


def _comma(value: Decimal | float, places: int = 1) -> str:
    return f"{float(value):,.{places}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _stamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _naive(value: datetime) -> datetime:
    """Local time without the zone, as the viewing form enters it."""
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value


def _same_time(left: datetime | None, right: datetime | None) -> bool:
    return _stamp(left) == _stamp(right)


# ─── Writing through one unit (SQL session or memory store) ──────────────────

def _put(unit: archive.Unit, collection: str, item: Any) -> None:
    """Insert or update a record of a store collection inside the unit."""
    if unit.db is None:
        unit.insert(getattr(unit.store, collection), item.id, item)
        return
    orm = _ORM[collection]
    columns = {column.key for column in orm.__table__.columns}
    values = {key: (_stamp(value) if isinstance(value, datetime) else value)
              for key, value in item.model_dump().items() if key in columns}
    row = unit.db.get(orm, item.id)
    if row is None:
        unit.db.add(orm(**values))
    else:
        for name, value in values.items():
            if getattr(row, name) != value:
                setattr(row, name, value)
    unit.db.flush()


def _remove(unit: archive.Unit, collection: str, item_id: str) -> None:
    if unit.db is None:
        target = getattr(unit.store, collection)
        if item_id in target:
            unit.remove(target, item_id)
        return
    row = unit.db.get(_ORM[collection], item_id)
    if row is not None:
        unit.db.delete(row)
        unit.db.flush()


def _rows(unit: archive.Unit, collection: str, **where: Any) -> list[Any]:
    """Visible records of a collection whose fields equal `where`."""
    if unit.db is None:
        return [row for row in getattr(unit.store, collection).values()
                if all(getattr(row, key) == value for key, value in where.items())]
    orm, model = _ORM[collection], _MODELS[collection]
    keys = [column.key for column in orm.__table__.columns]
    return [model.model_validate({key: getattr(row, key) for key in keys})
            for row in unit.db.scalars(select(orm).filter_by(**where))]


def _project(unit: archive.Unit, project_id: str, *, lock: bool = False) -> RelettingProject:
    if unit.db is None:
        try:
            return unit.store.reletting_projects[project_id]
        except KeyError:
            raise _not_found() from None
    query = select(RelettingProjectORM).where(RelettingProjectORM.id == project_id)
    row = unit.db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise _not_found()
    return RelettingProject.model_validate({column.key: getattr(row, column.key)
                                            for column in RelettingProjectORM.__table__.columns})


def _open(project: RelettingProject) -> None:
    if project.status != "open":
        raise _conflict("Das Projekt ist abgeschlossen. Änderungen sind nicht mehr möglich.")


def _lead(unit: archive.Unit, project: RelettingProject, lead_id: str) -> Lead:
    try:
        lead = unit.store.get_lead(lead_id)
    except (NotFoundError, KeyError):
        raise _not_found("Bewerber") from None
    if lead.project_id != project.id:
        raise _not_found("Bewerber")
    return lead


def _unit_and_property(unit: archive.Unit, unit_id: str):
    try:
        apartment = unit.store.get_unit(unit_id)
        building = unit.store.get_property(apartment.property_id)
    except (NotFoundError, KeyError):
        raise _not_found("Einheit") from None
    return apartment, building


def _current_listing(unit: archive.Unit, unit_id: str) -> Listing | None:
    """The unit's newest listing that is not closed (made on the listings page or from a project)."""
    return max((item for item in unit.store.list_listings() if item.unit_id == unit_id and item.status != "closed"),
               key=lambda item: item.created_at, default=None)


# ─── Figures and the comparison ──────────────────────────────────────────────

def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def warm_rent(project: RelettingProject) -> Decimal | None:
    if project.target_rent is None:
        return None
    return _money(project.target_rent) + _money(project.service_charge) + _money(project.heating_charge)


def _has_pets(text: str | None) -> bool | None:
    if text is None:
        return None
    return text.strip().lower() not in _NO_PETS


def _criteria(project: RelettingProject, lead: Lead, viewings: list[ViewingAppointment]) -> list[dict]:
    """Each requirement of the project against the applicant: met, not met or still open."""
    result = []

    def add(key: str, label: str, state: str, detail: str) -> None:
        result.append({"key": key, "label": label, "state": state, "detail": detail})

    warm = warm_rent(project)
    factor = Decimal(str(project.income_factor or 3))
    label = f"Einkommen mindestens {_comma(factor)}-fache Warmmiete"
    if warm is None or warm <= 0:
        add("income", label, "open", "Angebotsmiete fehlt")
    elif lead.net_income is None:
        add("income", label, "open", "Einkommen nicht angegeben")
    else:
        ratio = _money(lead.net_income) / warm
        add("income", label, "met" if ratio >= factor else "not_met", f"{_comma(ratio)}-fache Warmmiete")
    if lead.household_size is None:
        add("persons", "Haushaltsgröße passt", "open", "nicht angegeben")
    elif project.max_persons is None:
        add("persons", "Haushaltsgröße passt", "met", f"{lead.household_size} Personen, keine Vorgabe")
    else:
        add("persons", "Haushaltsgröße passt", "met" if lead.household_size <= project.max_persons else "not_met",
            f"{lead.household_size} von höchstens {project.max_persons} Personen")
    if lead.move_in_date is None or project.available_from is None:
        add("move_in", "Einzug zum Bezugstermin (± 1 Monat)", "open",
            "Wunschtermin nicht angegeben" if lead.move_in_date is None else "Bezugstermin fehlt")
    else:
        gap = abs((lead.move_in_date - project.available_from).days)
        add("move_in", "Einzug zum Bezugstermin (± 1 Monat)", "met" if gap <= 31 else "not_met",
            f"gewünscht {day(lead.move_in_date)}")
    pets = _has_pets(lead.pets)
    if pets is None:
        add("pets", "Haustiere passen zur Vorgabe", "open", "nicht angegeben")
    elif not pets:
        add("pets", "Haustiere passen zur Vorgabe", "met", "keine Haustiere")
    elif project.pets == "not_allowed":
        add("pets", "Haustiere passen zur Vorgabe", "not_met", lead.pets or "")
    elif project.pets == "on_request":
        add("pets", "Haustiere passen zur Vorgabe", "open", f"{lead.pets} · nach Absprache")
    else:
        add("pets", "Haustiere passen zur Vorgabe", "met", lead.pets or "")
    present = [name for key, name in DOCUMENTS if getattr(lead, key)]
    add("documents", "Unterlagen vollständig", "met" if len(present) == len(DOCUMENTS) else "open",
        f"{len(present)} von {len(DOCUMENTS)}" + (f": fehlt {', '.join(n for k, n in DOCUMENTS if not getattr(lead, k))}"
                                                  if len(present) < len(DOCUMENTS) else ""))
    attended = [v for v in viewings if v.status == "completed"]
    planned = sorted((v for v in viewings if v.status == "scheduled"), key=lambda v: v.scheduled_at)
    if attended:
        add("viewing", "Besichtigung wahrgenommen", "met", f"am {day(attended[-1].scheduled_at.date())}")
    elif planned:
        add("viewing", "Besichtigung wahrgenommen", "open", f"geplant am {day(planned[0].scheduled_at.date())}")
    elif any(v.status == "no_show" for v in viewings):
        add("viewing", "Besichtigung wahrgenommen", "not_met", "nicht erschienen")
    else:
        add("viewing", "Besichtigung wahrgenommen", "open", "noch keine Besichtigung")
    return result


def _deletable(project: RelettingProject, lead: Lead) -> bool:
    return lead.status in CLOSED_OUT or project.status != "open"


def _applicant(project: RelettingProject, lead: Lead, viewings: list[ViewingAppointment],
               attachments: list[LeadAttachment], today: date) -> dict:
    criteria = _criteria(project, lead, viewings)
    warm = warm_rent(project)
    share = (warm / _money(lead.net_income) * 100) if warm and lead.net_income else None
    ratings = [v.rating for v in viewings if v.rating]
    decided = lead.decided_at.date() if lead.decided_at else None
    waited = (today - decided).days if decided and lead.status in CLOSED_OUT else None
    return {
        **lead.model_dump(mode="json"),
        "criteria": criteria,
        "met": sum(1 for c in criteria if c["state"] == "met"),
        "not_met": sum(1 for c in criteria if c["state"] == "not_met"),
        "rent_share": float(round(share, 1)) if share is not None else None,
        "viewing_rating": max(ratings) if ratings else None,
        "viewings": [v.model_dump(mode="json") for v in sorted(viewings, key=lambda v: v.scheduled_at)],
        "attachments": [a.model_dump(mode="json") for a in sorted(attachments, key=lambda a: (a.created_at, a.id))],
        "deletable": _deletable(project, lead),
        "days_since_decision": waited,
        "purge_due": waited is not None and waited >= PURGE_AFTER_DAYS,
    }


def _ordered(rows: list[dict]) -> list[dict]:
    # what the person compares first: open applicants, most requirements met, best impression
    state = {"accepted": 0, "rejected": 2, "withdrawn": 2}
    return sorted(rows, key=lambda r: (state.get(r["status"], 1), -r["met"], r["not_met"],
                                       -(r["rating"] or 0), -(r["viewing_rating"] or 0), r["created_at"]))


# ─── Reading ─────────────────────────────────────────────────────────────────

def _address(building: Any) -> str:
    return ", ".join(part for part in (building.address_line,
                                       " ".join(v for v in (building.postal_code, building.city) if v)) if part)


def _covering(contract: Any, today: date) -> bool:
    return (contract.status in ("active", "terminated") and contract.start_date <= today
            and (contract.end_date is None or contract.end_date >= today))


def _vacancies(unit: archive.Unit, open_units: set[str], today: date) -> list[dict]:
    """Units without a running tenancy today, or whose tenancy ends soon, and no open project."""
    contracts: dict[str, list[Any]] = {}
    for contract in unit.store.list_contracts():
        contracts.setdefault(contract.unit_id, []).append(contract)
    properties = {p.id: p for p in unit.store.list_properties()}
    result = []
    for apartment in unit.store.list_units():
        if apartment.id in open_units:
            continue
        own = contracts.get(apartment.id, [])
        running = [c for c in own if _covering(c, today)]
        ending = [c.end_date for c in running if c.end_date is not None]
        if running and not (len(ending) == len(running) and max(ending) <= today + timedelta(days=UPCOMING_DAYS)):
            continue
        ended = [c.end_date for c in own if c.end_date is not None and c.end_date < today]
        building = properties.get(apartment.property_id)
        result.append({
            "unit_id": apartment.id, "unit_label": apartment.label, "unit_type": apartment.unit_type,
            "property_id": apartment.property_id, "property_name": building.name if building else None,
            "area_sqm": apartment.area_sqm, "rooms": apartment.rooms, "cold_rent": apartment.cold_rent,
            "vacant_since": max(ended).isoformat() if not running and ended else None,
            "free_from": max(ending).isoformat() if running else None,
            "href": f"/units/{quote(apartment.id, safe='')}",
        })
    return sorted(result, key=lambda r: (r["free_from"] is not None, r["property_name"] or "", r["unit_label"] or ""))


def overview(store, actor_id: str) -> dict:
    today = local_today()
    with archive.work(store, actor_id) as unit:
        projects = _rows(unit, "reletting_projects")
        leads: dict[str, list[Lead]] = {}
        for lead in unit.store.list_leads():
            if lead.project_id:
                leads.setdefault(lead.project_id, []).append(lead)
        lead_project = {lead.id: project_id for project_id, group in leads.items() for lead in group}
        viewings: dict[str, list[ViewingAppointment]] = {}
        for viewing in unit.store.list_viewing_appointments():
            if viewing.lead_id in lead_project:
                viewings.setdefault(lead_project[viewing.lead_id], []).append(viewing)
        units = {u.id: u for u in unit.store.list_units()}
        properties = {p.id: p for p in unit.store.list_properties()}
        contracts = unit.store.list_contracts()
        current = datetime.now()              # viewings are kept in the office's local time, as entered
        rows = []
        for project in projects:
            apartment = units.get(project.unit_id)
            building = properties.get(apartment.property_id) if apartment else None
            group = leads.get(project.id, [])
            planned = sorted(when for when in (_naive(v.scheduled_at) for v in viewings.get(project.id, [])
                                               if v.status == "scheduled") if when >= current)
            warm = warm_rent(project)
            steps = _steps(project, _missing_for_ad(project, apartment) if apartment else [], group,
                           viewings.get(project.id, []), _signed(project, contracts))
            due = [lead for lead in group if lead.status in CLOSED_OUT and lead.decided_at
                   and (today - lead.decided_at.date()).days >= PURGE_AFTER_DAYS]
            rows.append({
                "id": project.id, "status": project.status, "unit_id": project.unit_id,
                "unit_label": apartment.label if apartment else None,
                "property_id": apartment.property_id if apartment else None,
                "property_name": building.name if building else None,
                "available_from": project.available_from.isoformat() if project.available_from else None,
                "warm_rent": float(warm) if warm is not None else None,
                "applicants": len([lead for lead in group if lead.status not in CLOSED_OUT]),
                "declined": len([lead for lead in group if lead.status in CLOSED_OUT]),
                "purge_due": len(due),
                "next_viewing": planned[0].isoformat() if planned else None,
                "accepted": next((lead.full_name for lead in group if lead.status == "accepted"), None),
                "next_step": _next_step(project, steps),
                "created_at": project.created_at.isoformat(), "closed_at": project.closed_at.isoformat()
                if project.closed_at else None,
                "href": f"/reletting/{quote(project.id, safe='')}",
            })
        rows.sort(key=lambda r: (r["status"] != "open", r["available_from"] or "9999", r["created_at"]))
        open_units = {p.unit_id for p in projects if p.status == "open"}
        vacant = _vacancies(unit, open_units, today)
        return {
            "projects": rows,
            "vacancies": vacant,
            "totals": {"open": sum(1 for r in rows if r["status"] == "open"),
                       "vacant_without_project": len(vacant),
                       "applicants": sum(r["applicants"] for r in rows if r["status"] == "open"),
                       "purge_due": sum(r["purge_due"] for r in rows)},
        }


def _missing_for_ad(project: RelettingProject, apartment: Any) -> list[str]:
    missing = []
    if not project.headline:
        missing.append("Überschrift")
    if project.target_rent is None:
        missing.append("Kaltmiete")
    if not apartment.area_sqm:
        missing.append("Wohnfläche (an der Einheit)")
    if project.available_from is None:
        missing.append("Bezugsfrei ab")
    if project.energy_certificate is None:
        missing.append("Art des Energieausweises")
    elif project.energy_certificate != "none":
        for value, label in ((project.energy_value, "Energiekennwert"), (project.energy_carrier, "Energieträger"),
                             (project.year_built, "Baujahr laut Energieausweis")):
            if value in (None, ""):
                missing.append(label)
    return missing


def _signed(project: RelettingProject, contracts: Iterable[Any]) -> Any | None:
    """A contract made for the unit with the accepted applicant while the project still runs."""
    if project.status != "open" or project.tenant_id is None:
        return None
    return next((c for c in contracts if c.unit_id == project.unit_id and c.tenant_id == project.tenant_id
                 and c.status in ("active", "draft")), None)


def _contract_step(project: RelettingProject, signed: Any | None) -> str:
    if project.contract_id:
        return "Vertrag verknüpft, Projekt abgeschlossen"
    if signed is not None:
        return f"Vertrag {signed.contract_number} angelegt: Projekt damit abschließen"
    return "Vertrag anlegen und verknüpfen"


def _steps(project: RelettingProject, missing: list[str], leads: list[Lead],
           viewings: list[ViewingAppointment], signed: Any | None = None) -> list[dict]:
    attended = sum(1 for v in viewings if v.status == "completed")
    remaining = [lead for lead in leads if lead.status != "accepted"]
    accepted = next((lead for lead in leads if lead.status == "accepted"), None)
    return [
        {"key": "offer", "label": "Angebot festlegen",
         "done": project.target_rent is not None and project.available_from is not None,
         "detail": "Miete, Nebenkosten, Kaution, Bezugstermin und Vorgaben"},
        {"key": "expose", "label": "Exposé und Portaltext", "done": not missing,
         "detail": "Alle Pflichtangaben vorhanden" if not missing else "Es fehlt: " + ", ".join(missing)},
        {"key": "applicants", "label": "Interessenten erfassen", "done": bool(leads),
         "detail": f"{len(leads)} Bewerbungen" if leads else "Noch keine Bewerbung"},
        {"key": "viewings", "label": "Besichtigungen", "done": attended > 0,
         "detail": f"{attended} wahrgenommen" if attended else "Noch keine Besichtigung wahrgenommen"},
        {"key": "choice", "label": "Bewerber auswählen", "done": accepted is not None,
         "detail": f"Übernommen: {accepted.full_name}" if accepted else "Vergleich nach einheitlichen Kriterien"},
        {"key": "contract", "label": "Mietvertrag", "done": project.contract_id is not None,
         "detail": _contract_step(project, signed)},
        {"key": "privacy", "label": "Bewerberdaten löschen", "done": project.status != "open" and not remaining,
         "detail": (f"{project.deleted_applicants} Bewerbungen datenschutzkonform gelöscht"
                    if not remaining else f"{len(remaining)} Bewerbungen noch gespeichert")},
    ]


def _next_step(project: RelettingProject, steps: list[dict]) -> dict | None:
    """What to do next: the step after the furthest one done (earlier gaps stay visible in the project)."""
    if project.status == "cancelled":
        pending = [step for step in steps if step["key"] == "privacy" and not step["done"]]
    else:
        done = [index for index, step in enumerate(steps) if step["done"]]
        start = done[-1] + 1 if done else 0
        pending = [step for step in steps[start:] if not step["done"]]
        if project.status == "open" and steps[0]["done"] is False:
            pending = [steps[0]]                   # without rent and date there is nothing to offer
    if not pending:
        return None
    step = pending[0]
    return {"key": step["key"], "label": step["label"], "detail": step["detail"]}


def _detail(unit: archive.Unit, project: RelettingProject) -> dict:
    today = local_today()
    apartment, building = _unit_and_property(unit, project.unit_id)
    leads = _rows(unit, "leads", project_id=project.id)
    ids = {lead.id for lead in leads}
    viewings = [v for v in unit.store.list_viewing_appointments() if v.lead_id in ids]
    attachments = [a for a in _rows(unit, "lead_attachments") if a.lead_id in ids]
    by_lead_viewings: dict[str, list[ViewingAppointment]] = {}
    for viewing in viewings:
        by_lead_viewings.setdefault(viewing.lead_id, []).append(viewing)
    by_lead_files: dict[str, list[LeadAttachment]] = {}
    for attachment in attachments:
        by_lead_files.setdefault(attachment.lead_id, []).append(attachment)
    applicants = _ordered([_applicant(project, lead, by_lead_viewings.get(lead.id, []), by_lead_files.get(lead.id, []),
                                      today) for lead in leads])
    names = {lead.id: lead.full_name for lead in leads}
    missing = _missing_for_ad(project, apartment)
    listing = None
    if project.listing_id:
        try:
            listing = unit.store.get_listing(project.listing_id).model_dump(mode="json")
        except (NotFoundError, KeyError):
            listing = None
    elif project.status == "open":
        # a listing made on the listings page meanwhile is the one "Inserat aktualisieren" takes over
        found = _current_listing(unit, project.unit_id)
        listing = found.model_dump(mode="json") if found else None
    tenant = None
    if project.tenant_id:
        try:
            found = unit.store.get_tenant(project.tenant_id)
            tenant = {"id": found.id, "full_name": found.full_name,
                      "href": f"/tenants/{quote(found.id, safe='')}/account"}
        except (NotFoundError, KeyError):
            tenant = None
    contracts = [c for c in unit.store.list_contracts() if c.unit_id == project.unit_id
                 and (project.tenant_id is None or c.tenant_id == project.tenant_id) and c.status in ("active", "draft")]
    warm = warm_rent(project)
    steps = _steps(project, missing, leads, viewings, _signed(project, contracts))
    return {
        "project": project.model_dump(mode="json"),
        "warm_rent": float(warm) if warm is not None else None,
        "unit": {"id": apartment.id, "label": apartment.label, "unit_type": apartment.unit_type,
                 "area_sqm": apartment.area_sqm, "rooms": apartment.rooms, "floor": apartment.floor,
                 "features": apartment.features, "cold_rent": apartment.cold_rent,
                 "href": f"/units/{quote(apartment.id, safe='')}"},
        "property": {"id": building.id, "name": building.name, "address": _address(building),
                     "year_built": building.year_built, "href": f"/properties/{quote(building.id, safe='')}"},
        "steps": steps,
        "next_step": _next_step(project, steps),
        "missing_for_ad": missing,
        "applicants": applicants,
        "viewings": [{**v.model_dump(mode="json"), "lead_name": names.get(v.lead_id)}
                     for v in sorted(viewings, key=lambda v: v.scheduled_at)],
        "listing": listing,
        "tenant": tenant,
        "contracts": [{"id": c.id, "contract_number": c.contract_number, "start_date": c.start_date.isoformat(),
                       "status": c.status, "tenant_id": c.tenant_id} for c in contracts],
        "purge_due": sum(1 for row in applicants if row["purge_due"]),
        "retention_days": PURGE_AFTER_DAYS,
    }


def detail(store, project_id: str, actor_id: str) -> dict:
    with archive.work(store, actor_id) as unit:
        return _detail(unit, _project(unit, project_id))


# ─── The project ─────────────────────────────────────────────────────────────

def start(store, payload: RelettingStart, actor_id: str) -> dict:
    """Open the project of a unit, prefilled from the unit, its building and the previous offer."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        apartment, building = _unit_and_property(unit, payload.unit_id)
        projects = _rows(unit, "reletting_projects", unit_id=apartment.id)
        if any(p.status == "open" for p in projects):
            raise _conflict("Für diese Einheit läuft bereits ein Neuvermietungsprojekt.")
        previous = max(projects, key=lambda p: p.created_at, default=None)
        today = local_today()
        running = [c for c in unit.store.list_contracts() if c.unit_id == apartment.id and _covering(c, today)]
        free = max((c.end_date for c in running if c.end_date), default=None)
        kind = KINDS.get((apartment.unit_type or "wohnung").strip().lower(), "Mietobjekt")
        rooms = (_comma(apartment.rooms).removesuffix(",0") + "-Zimmer-") if apartment.rooms and kind == "Wohnung" else ""
        stamp = now()
        # the texts, requirements and energy figures of the unit's previous project are a good start
        carried = {key: value for key, value in (previous.model_dump(include={
            "income_factor", "max_persons", "pets", "headline", "description", "location_text", "features_text",
            "energy_certificate", "energy_value", "energy_class", "energy_carrier", "heating_type", "year_built",
            "contact_name", "contact_phone", "contact_email"}) if previous else {}).items() if value is not None}
        project = RelettingProject.model_validate({
            "id": new_id(), "unit_id": apartment.id, "status": "open",
            "available_from": (free + timedelta(days=1)) if free else None,
            "target_rent": apartment.cold_rent, "service_charge": apartment.service_charge_advance,
            "heating_charge": apartment.heating_advance,
            "deposit_amount": float(_money(apartment.cold_rent) * 3) if apartment.cold_rent else None,
            "headline": f"{rooms}{kind} in {building.city}" if building.city else None,
            "year_built": building.year_built, "features_text": apartment.features,
            "created_at": stamp, "updated_at": stamp, **carried})
        # the unit's current listing and the inquiries already recorded for it (on the Interessenten
        # page or from the listing) belong to the project; decided ones stay with the earlier letting
        current = _current_listing(unit, apartment.id)
        if current is not None:
            project = project.model_copy(update={"listing_id": current.id})
        _put(unit, "reletting_projects", project)
        own = {item.id for item in unit.store.list_listings() if item.unit_id == apartment.id}
        adopted = 0
        for lead in unit.store.list_leads():
            if (lead.project_id is None and lead.status not in DECIDED
                    and (lead.unit_id == apartment.id or (lead.unit_id is None and lead.listing_id in own))):
                _put(unit, "leads", lead.model_copy(update={"project_id": project.id, "unit_id": apartment.id,
                                                            "updated_at": stamp}))
                adopted += 1
        return {**_detail(unit, project), "adopted": adopted}


def open_project_id(store: Any, unit_id: str | None) -> str | None:
    """The running re-letting project of a unit: a new inquiry for the unit belongs to it."""
    if not unit_id:
        return None
    return next((p.id for p in store.list_reletting_projects() if p.unit_id == unit_id and p.status == "open"), None)


def update(store, project_id: str, payload: RelettingUpdate, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        if payload.base_updated_at is not None and not _same_time(payload.base_updated_at, project.updated_at):
            raise _conflict("Das Projekt wurde inzwischen geändert. Bitte neu laden.")
        values = payload.model_dump(exclude={"base_updated_at"})
        project = project.model_copy(update={**values, "updated_at": now()})
        _put(unit, "reletting_projects", project)
        return _detail(unit, project)


def _finish(unit: archive.Unit, project: RelettingProject, status: str, **changes: Any) -> RelettingProject:
    stamp = now()
    project = project.model_copy(update={"status": status, "closed_at": stamp, "updated_at": stamp, **changes})
    _put(unit, "reletting_projects", project)
    if project.listing_id:
        try:
            listing = unit.store.get_listing(project.listing_id)
        except (NotFoundError, KeyError):
            listing = None
        if listing is not None and listing.status != "closed":
            _put(unit, "listings", listing.model_copy(update={"status": "closed", "updated_at": stamp}))
    return project


def close(store, project_id: str, payload: CloseRequest, actor_id: str) -> dict:
    """The unit is let: link the new contract and close the project."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        try:
            contract = unit.store.get_contract(payload.contract_id)
        except (NotFoundError, KeyError):
            raise _not_found("Mietvertrag") from None
        if contract.unit_id != project.unit_id:
            raise _conflict("Der Vertrag gehört nicht zur angebotenen Einheit.")
        if project.tenant_id and contract.tenant_id != project.tenant_id:
            raise _conflict("Der Vertrag ist nicht mit dem übernommenen Bewerber geschlossen.")
        if contract.status not in ("active", "draft"):
            raise _conflict("Der Vertrag ist nicht mehr gültig.")
        project = _finish(unit, project, "closed", contract_id=contract.id, tenant_id=contract.tenant_id)
        return _detail(unit, project)


def cancel(store, project_id: str, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        return _detail(unit, _finish(unit, project, "cancelled"))


# ─── Applicants and viewings ─────────────────────────────────────────────────

def decision_time(previous: str | None, status: str, decided_at: datetime | None) -> datetime | None:
    """When an applicant was accepted, declined or withdrew (the deletion hint counts from it)."""
    if status not in DECIDED:
        return None
    return decided_at if previous == status and decided_at else now()


def add_applicant(store, project_id: str, payload: ApplicantInput, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        if payload.status == "accepted":
            raise _conflict("Bewerber bitte über „Als Mieter übernehmen“ auswählen.")
        stamp = now()
        values = payload.model_dump(exclude={"base_updated_at"})
        lead = Lead(id=new_id(), project_id=project.id, unit_id=project.unit_id, listing_id=project.listing_id,
                    priority=0, decided_at=decision_time(None, payload.status, None), created_at=stamp, updated_at=stamp,
                    **values)
        _put(unit, "leads", lead)
        return _detail(unit, project)


def update_applicant(store, project_id: str, lead_id: str, payload: ApplicantInput, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        lead = _lead(unit, project, lead_id)
        if payload.base_updated_at is not None and not _same_time(payload.base_updated_at, lead.updated_at):
            raise _conflict("Die Bewerbung wurde inzwischen geändert. Bitte neu laden.")
        if (payload.status == "accepted") != (lead.status == "accepted"):
            raise _conflict("Die Übernahme als Mieter ändert nur „Als Mieter übernehmen“.")
        values = payload.model_dump(exclude={"base_updated_at"})
        lead = lead.model_copy(update={**values, "decided_at": decision_time(lead.status, payload.status, lead.decided_at),
                                       "updated_at": now()})
        _put(unit, "leads", lead)
        return _detail(unit, project)


def reject(store, project_id: str, payload: RejectRequest, actor_id: str) -> dict:
    """Decline applicants (no message is sent; the office informs them itself)."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        stamp = now()
        for lead_id in dict.fromkeys(payload.lead_ids):
            lead = _lead(unit, project, lead_id)
            if lead.status == "accepted":
                raise _conflict(f"{lead.full_name} ist als Mieter übernommen und kann nicht abgesagt werden.")
            if lead.status not in CLOSED_OUT:
                _put(unit, "leads", lead.model_copy(update={"status": "rejected", "decided_at": stamp,
                                                            "updated_at": stamp}))
        return _detail(unit, project)


def _viewing_lead(unit: archive.Unit, project: RelettingProject, lead_id: str) -> Lead:
    lead = _lead(unit, project, lead_id)
    if lead.status in CLOSED_OUT:
        raise _conflict("Für abgesagte Bewerber wird keine Besichtigung geplant.")
    return lead


def add_viewing(store, project_id: str, payload: ViewingInput, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        lead = _viewing_lead(unit, project, payload.lead_id)
        stamp = now()
        viewing = ViewingAppointment(id=new_id(), unit_id=project.unit_id, created_at=stamp, updated_at=stamp,
                                     **payload.model_dump())
        _put(unit, "viewing_appointments", viewing)
        if lead.status in ("new", "contacted") and payload.status == "scheduled":
            _put(unit, "leads", lead.model_copy(update={"status": "viewing_scheduled", "updated_at": stamp}))
        return _detail(unit, project)


def update_viewing(store, project_id: str, viewing_id: str, payload: ViewingInput, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        try:
            viewing = unit.store.get_viewing_appointment(viewing_id)
        except (NotFoundError, KeyError):
            raise _not_found("Besichtigung") from None
        _lead(unit, project, viewing.lead_id)
        if payload.lead_id != viewing.lead_id:
            raise _conflict("Eine Besichtigung bleibt beim Bewerber, für den sie geplant wurde.")
        viewing = viewing.model_copy(update={**payload.model_dump(), "updated_at": now()})
        _put(unit, "viewing_appointments", viewing)
        return _detail(unit, project)


# ─── Taking the chosen applicant over ────────────────────────────────────────

def accept(store, project_id: str, payload: AcceptRequest, actor_id: str) -> dict:
    """The chosen applicant becomes the tenant: a tenant record and what the new contract starts from."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        lead = _lead(unit, project, payload.lead_id)
        if lead.status in CLOSED_OUT:
            raise _conflict("Ein abgesagter Bewerber kann nicht übernommen werden.")
        others = [row for row in _rows(unit, "leads", project_id=project.id)
                  if row.status == "accepted" and row.id != lead.id]
        if others:
            raise _conflict(f"Für dieses Projekt ist bereits {others[0].full_name} als Mieter übernommen.")
        stamp = now()
        if payload.tenant_id:
            try:
                tenant = unit.store.get_tenant(payload.tenant_id)
            except (NotFoundError, KeyError):
                raise _not_found("Mieter") from None
        elif project.tenant_id and lead.status == "accepted":
            tenant = unit.store.get_tenant(project.tenant_id)
        else:
            tenant = Tenant(id=new_id(), full_name=lead.full_name, email=lead.email, phone=lead.phone,
                            notes=f"Aus der Neuvermietung übernommen am {day(stamp.date())}.",
                            created_at=stamp, updated_at=stamp)
            _put(unit, "tenants", tenant)
        _put(unit, "leads", lead.model_copy(update={"status": "accepted", "decided_at": stamp, "updated_at": stamp}))
        apartment, building = _unit_and_property(unit, project.unit_id)
        rent_applied = False
        if payload.apply_rent and project.target_rent is not None:
            changes = {"cold_rent": project.target_rent, "service_charge_advance": project.service_charge,
                       "heating_advance": project.heating_charge}
            if any(getattr(apartment, key) != value for key, value in changes.items()):
                _put(unit, "units", Unit.model_validate({**apartment.model_dump(), **changes, "updated_at": stamp}))
                rent_applied = True
        project = project.model_copy(update={"tenant_id": tenant.id, "updated_at": stamp})
        _put(unit, "reletting_projects", project)
        start_day = max(filter(None, (project.available_from, lead.move_in_date)), default=None)
        prefill = {"property_id": building.id, "unit_id": apartment.id, "tenant_id": tenant.id, "status": "active",
                   "start_date": start_day.isoformat() if start_day else None,
                   "deposit_amount": project.deposit_amount, "persons": lead.household_size}
        return {**_detail(unit, project), "contract_prefill": {k: v for k, v in prefill.items() if v is not None},
                "rent_applied": rent_applied}


# ─── Deleting applicants' data ───────────────────────────────────────────────

def _drop_traces(unit: archive.Unit, lead_ids: set[str], viewing_ids: set[str]) -> None:
    """Shared notes, field history and marketing receipts that name the deleted applicants."""
    subjects = {("lead", i) for i in lead_ids} | {("viewing", i) for i in viewing_ids}
    if unit.db is None:
        raw = object.__getattribute__(unit.store, "__dict__")
        for collection in ("business_conversation_notes", "change_history"):
            for key, row in list(raw[collection].items()):
                if (row.entity_type, row.entity_id) in subjects:
                    unit.remove(raw[collection], key)
        for key, row in list(raw["business_qol_commands"].items()):
            if row.operation.startswith("marketing:") and _names(row.response, lead_ids):
                unit.remove(raw["business_qol_commands"], key)
        return
    for kind, ids in (("lead", lead_ids), ("viewing", viewing_ids)):
        if ids:
            unit.db.execute(delete(ConversationNoteORM).where(ConversationNoteORM.entity_type == kind,
                                                              ConversationNoteORM.entity_id.in_(ids)))
            unit.db.execute(delete(ChangeHistoryORM).where(ChangeHistoryORM.entity_type == kind,
                                                           ChangeHistoryORM.entity_id.in_(ids)))
    for command in unit.db.scalars(select(BusinessCommandORM).where(BusinessCommandORM.operation.like("marketing:%"))):
        if _names(command.response, lead_ids):
            unit.db.delete(command)
    unit.db.flush()


def _names(response: Any, lead_ids: Iterable[str]) -> bool:
    text = json.dumps(response, default=str)
    return any(lead_id in text for lead_id in lead_ids)


def purge(store, project_id: str, payload: PurgeRequest, actor_id: str) -> tuple[dict, list[str]]:
    """Delete applicants with their viewings, documents, notes and history; returns the files to remove."""
    if not payload.confirmed:
        raise HTTPException(422, "Bitte das endgültige Löschen bestätigen.")
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        leads = [_lead(unit, project, lead_id) for lead_id in dict.fromkeys(payload.lead_ids)]
        kept = [lead.full_name for lead in leads if not _deletable(project, lead)]
        if kept:
            raise _conflict("Nur abgesagte oder zurückgezogene Bewerbungen lassen sich löschen, solange das Projekt "
                            "läuft: " + ", ".join(kept))
        ids = {lead.id for lead in leads}
        viewings = {v.id for v in unit.store.list_viewing_appointments() if v.lead_id in ids}
        files = []
        for attachment in [a for a in _rows(unit, "lead_attachments") if a.lead_id in ids]:
            files.append(attachment.file_url)
            _remove(unit, "lead_attachments", attachment.id)
        for viewing_id in viewings:
            _remove(unit, "viewing_appointments", viewing_id)
        _drop_traces(unit, ids, viewings)
        for lead in leads:
            _remove(unit, "leads", lead.id)
        project = project.model_copy(update={"deleted_applicants": project.deleted_applicants + len(leads),
                                             "updated_at": now()})
        _put(unit, "reletting_projects", project)
        return {**_detail(unit, project), "deleted": len(leads), "deleted_files": len(files)}, files


# ─── Applicants' documents ───────────────────────────────────────────────────

def attachment_target(store, project_id: str, lead_id: str, actor_id: str) -> None:
    """Check before the upload is stored that the applicant exists and may be changed."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id)
        _open(project)
        _lead(unit, project, lead_id)


def add_attachment(store, project_id: str, lead_id: str, *, kind: Literal["document", "photo"], title: str,
                   file_url: str, size: int,
                   actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        _lead(unit, project, lead_id)
        attachment = LeadAttachment(id=new_id(), lead_id=lead_id, kind=kind, title=title[:200] or "Unterlage",
                                    file_url=file_url, size=size, created_at=now())
        _put(unit, "lead_attachments", attachment)
        return _detail(unit, project)


def remove_attachment(store, project_id: str, attachment_id: str, actor_id: str) -> tuple[dict, str]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        found = next((a for a in _rows(unit, "lead_attachments", id=attachment_id)), None)
        if found is None:
            raise _not_found("Unterlage")
        _lead(unit, project, found.lead_id)
        _remove(unit, "lead_attachments", found.id)
        return _detail(unit, project), found.file_url


def lead_files(store, lead_id: str) -> list[str]:
    """The stored files of a lead's attachments (removed with the lead)."""
    return [a.file_url for a in store.list_lead_attachments() if a.lead_id == lead_id]


# ─── Offer texts, listing and the AI question ────────────────────────────────

def _facts(project: RelettingProject, apartment: Any) -> list[tuple[str, str]]:
    warm = warm_rent(project)
    rows: list[tuple[str, str | None]] = [("Wohnfläche", f"{_comma(apartment.area_sqm)} m²" if apartment.area_sqm else None),
            ("Zimmer", _comma(apartment.rooms).removesuffix(",0") if apartment.rooms else None),
            ("Etage", apartment.floor),
            ("Bezugsfrei ab", day(project.available_from) if project.available_from else None),
            ("Kaltmiete", eur(project.target_rent) if project.target_rent is not None else None),
            ("Nebenkosten (Vorauszahlung)", eur(project.service_charge) if project.service_charge is not None else None),
            ("Heizkosten (Vorauszahlung)", eur(project.heating_charge) if project.heating_charge is not None else None),
            ("Warmmiete", eur(warm) if warm is not None else None),
            ("Kaution", eur(project.deposit_amount) if project.deposit_amount is not None else None),
            ("Haustiere", PETS.get(project.pets or "")),
            ("Personen höchstens", str(project.max_persons) if project.max_persons else None)]
    return [(label, value) for label, value in rows if value is not None and value != ""]


def _energy(project: RelettingProject) -> list[tuple[str, str]]:
    if project.energy_certificate is None:
        return []
    rows: list[tuple[str, str | None]] = [("Energieausweis", CERTIFICATES[project.energy_certificate])]
    if project.energy_certificate != "none":
        measure = "Endenergieverbrauch" if project.energy_certificate == "consumption" else "Endenergiebedarf"
        rows += [(measure, f"{_comma(project.energy_value)} kWh/(m²·a)" if project.energy_value is not None else None),
                 ("Energieeffizienzklasse", project.energy_class),
                 ("Wesentlicher Energieträger", project.energy_carrier),
                 ("Baujahr laut Energieausweis", str(project.year_built) if project.year_built else None)]
    rows.append(("Heizungsart", project.heating_type))
    return [(label, value) for label, value in rows if value is not None and value != ""]


def _offer(unit: archive.Unit, project: RelettingProject) -> dict:
    apartment, building = _unit_and_property(unit, project.unit_id)
    return {"project": project, "unit": apartment, "property": building,
            "facts": _facts(project, apartment), "energy": _energy(project),
            "missing": _missing_for_ad(project, apartment)}


def _lines(rows: list[tuple[str, str]]) -> str:
    return "\n".join(f"{label}: {value}" for label, value in rows)


def portal_text(store, project_id: str, actor_id: str) -> dict:
    """The texts for a portal's form, block by block for copy and paste (nothing is sent)."""
    with archive.work(store, actor_id) as unit:
        offer = _offer(unit, _project(unit, project_id))
        project, building = offer["project"], offer["property"]
        contact = "\n".join(v for v in (project.contact_name, project.contact_phone, project.contact_email) if v)
        blocks = [
            ("title", "Überschrift", project.headline or ""),
            ("facts", "Eckdaten und Kosten", _lines(offer["facts"])),
            ("description", "Objektbeschreibung", project.description or ""),
            ("features", "Ausstattung", project.features_text or ""),
            ("location", "Lage", project.location_text or (f"{building.postal_code or ''} {building.city or ''}".strip())),
            ("energy", "Energieausweis (Pflichtangaben)", _lines(offer["energy"])),
            ("contact", "Kontakt", contact),
        ]
        whole = "\n\n".join(f"{label}\n{text}" if key != "title" else text for key, label, text in blocks if text)
        return {"blocks": [{"key": key, "label": label, "text": text} for key, label, text in blocks]
                + [{"key": "all", "label": "Alles zusammen", "text": whole}],
                "missing": offer["missing"]}


def expose(store, project_id: str, actor_id: str) -> tuple[bytes, str]:
    from .reletting_render import render_expose

    with archive.work(store, actor_id) as unit:
        offer = _offer(unit, _project(unit, project_id))
        photos = [p for p in unit.store.list_entity_photos("unit", offer["unit"].id)]
        photos += [p for p in unit.store.list_entity_photos("property", offer["property"].id)]
        if offer["project"].listing_id:
            photos += [p for p in unit.store.list_listing_photos() if p.listing_id == offer["project"].listing_id]
        pdf = render_expose(offer, photos)
        name = "Expose-" + "".join(c if c.isalnum() else "-" for c in (offer["unit"].label or "Einheit")) + ".pdf"
        return pdf, name


def link_listing(store, project_id: str, actor_id: str) -> dict:
    """Create the listing of the project (or bring the linked one up to date); publishing stays explicit."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        project = _project(unit, project_id, lock=True)
        _open(project)
        offer = _offer(unit, project)
        stamp = now()
        text = "\n\n".join(part for part in (project.description, project.features_text and
                                             "Ausstattung\n" + project.features_text,
                                             project.location_text and "Lage\n" + project.location_text,
                                             offer["energy"] and "Energieausweis\n" + _lines(offer["energy"]))
                         if part)
        charges = (_money(project.service_charge) + _money(project.heating_charge)
                   if project.service_charge is not None or project.heating_charge is not None else None)
        values: dict[str, Any] = {"title": project.headline or offer["unit"].label, "description": text or None,
                  "target_rent": project.target_rent, "service_charge": float(charges) if charges is not None else None,
                  "available_from": project.available_from, "contact_name": project.contact_name,
                  "contact_email": project.contact_email}
        current = None
        if project.listing_id:
            try:
                current = unit.store.get_listing(project.listing_id)
            except (NotFoundError, KeyError):
                current = None
        if current is None:
            current = _current_listing(unit, project.unit_id)    # one made on the listings page meanwhile
        if current is None:
            listing = Listing(id=new_id(), unit_id=project.unit_id, status="draft", created_at=stamp,
                              updated_at=stamp, **values)
        else:
            listing = current.model_copy(update={**values, "updated_at": stamp})
        _put(unit, "listings", listing)
        if project.listing_id != listing.id:
            project = project.model_copy(update={"listing_id": listing.id, "updated_at": stamp})
            _put(unit, "reletting_projects", project)
            for lead in _rows(unit, "leads", project_id=project.id):
                if lead.listing_id is None:
                    _put(unit, "leads", lead.model_copy(update={"listing_id": listing.id}))
        return {**_detail(unit, project), "listing_href": f"/listings?focus_id={quote(listing.id, safe='')}"}


def ai_question(store, project_id: str, actor_id: str) -> dict:
    """A comparison question without names, contact data or free notes, for the person to send in the assistant."""
    with archive.work(store, actor_id) as unit:
        project = _project(unit, project_id)
        data = _detail(unit, project)
    rows = [row for row in data["applicants"] if row["status"] not in CLOSED_OUT]
    if not rows:
        raise _conflict("Es gibt noch keine offene Bewerbung zum Vergleichen.")
    warm = data["warm_rent"]
    lines = [
        "Bitte vergleiche die folgenden Bewerbungen für eine Wohnung nachvollziehbar anhand der genannten Kriterien "
        "und nenne für jede Bewerbung Stärken, offene Punkte und was vor einer Entscheidung noch zu klären ist.",
        "Entscheidungen dürfen nicht auf Merkmale nach § 1 AGG (ethnische Herkunft, Geschlecht, Religion oder "
        "Weltanschauung, Behinderung, Alter, sexuelle Identität) gestützt werden; die Bewerbungen sind pseudonymisiert.",
        "",
        "Angebot:",
        f"- Warmmiete: {eur(warm)}" if warm is not None else "- Warmmiete: noch offen",
        f"- Einkommensvorgabe: mindestens {_comma(project.income_factor)}-fache Warmmiete",
        f"- Bezugsfrei ab: {day(project.available_from)}" if project.available_from else "- Bezugstermin: offen",
        f"- Personen höchstens: {project.max_persons}" if project.max_persons else "- Personen: keine Vorgabe",
        f"- Haustiere: {PETS.get(project.pets or '', 'keine Vorgabe')}",
        "",
    ]
    for index, row in enumerate(rows):
        letter = chr(ord("A") + index) if index < 26 else f"{index + 1}"
        lines.append(f"Bewerbung {letter}:")
        for criterion in row["criteria"]:
            state = {"met": "erfüllt", "not_met": "nicht erfüllt", "open": "offen"}[criterion["state"]]
            lines.append(f"- {criterion['label']}: {state} ({criterion['detail']})")
        if row.get("employment"):
            lines.append(f"- Beschäftigung: {EMPLOYMENT[row['employment']]}")
        if row.get("rent_share") is not None:
            lines.append(f"- Anteil der Warmmiete am Nettoeinkommen: {_comma(row['rent_share'])} %")
        if row.get("viewing_rating"):
            lines.append(f"- Eindruck bei der Besichtigung: {row['viewing_rating']} von 5")
        if row.get("rating"):
            lines.append(f"- Eigene Bewertung: {row['rating']} von 5")
        lines.append("")
    return {"question": "\n".join(lines).strip(), "applicants": len(rows)}
