"""Read-only guidance from authoritative invoice, maintenance and tenancy records.

No lifecycle state is written here. Each linked service remains responsible for
permissions, revisions, transitions and financial calculations at execution time.
"""
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from ..db.orm_models import Base
from ..domain.clock import local_today
from ..permissions import may_write
from . import document_versions as archive
from .maintenance_rows import Rows


def records(store, table_name, **where):
    if hasattr(store, "db"):
        table = Base.metadata.tables[table_name]
        query = select(table)
        for key, value in where.items():
            query = query.where(table.c[key] == value)
        return [SimpleNamespace(**dict(row)) for row in store.db.execute(query).mappings()]
    return [row for row in getattr(store, table_name).values()
            if all(getattr(row, key) == value for key, value in where.items())]


def _unit(store):
    return archive.Unit(store, getattr(store, "db", None), {}, None if hasattr(store, "db") else archive.memory_archive(store))


def _action(user, label, href, area, *, blocked=None):
    allowed = may_write(user["role"], area)
    return {"id": "next", "label": label, "href": href, "allowed": allowed and not blocked,
            "reason": blocked or (None if allowed else "Für diesen Schritt fehlt die Schreibberechtigung.")}


def _base(flow, stage, action, blockers, *, waiting=None, assignee=None, deadline=None, completed=False):
    return {"flow": flow, "stage": stage, "next_action": action, "blockers": blockers,
            "waiting_for": waiting, "assignee": assignee, "deadline_basis": deadline, "completed": completed}


def invoice(store, row, user):
    from . import invoice_review, payment_security
    view = invoice_review.review_view(store, row.id, user)
    review = view["review"]
    href = f"/invoice-review/{row.id}"
    blockers: list[str] = []
    waiting = None
    path = f"/invoices/{row.id}/review"
    if review is None:
        stage, label, area = "receipt", "Rechnungseingang erfassen", path
    elif review["status"] == "rejected":
        stage, label, area = "rejected", "Ablehnungsnachweis ansehen", path
    elif review["status"] == "query":
        stage, label, area = "query", "Antwort prüfen und Prüfungen erneuern", path
        waiting = review["decision_reason"] or "Antwort zur Rückfrage"
    elif review["status"] in ("approved", "partially_approved"):
        gate = payment_security.proposal_gate(store, row.id)
        if view["settlement"]["payment_status"] == "overpaid":
            stage, label, area = "overpayment", "Überzahlung klären und Rückzahlung zuordnen", path
            blockers = ["Die verbuchten Zahlungen übersteigen den freigegebenen Zahlbetrag."]
        elif view["settlement"]["payment_status"] == "paid":
            stage, label, area = "paid", "Zahlungsnachweise ansehen", path
        elif view["kind"] == "credit_note":
            stage, label, area = "credit", "Gutschrift und Ursprungsrechnung ansehen", path
        elif gate["authorized"]:
            stage, label, area = "proposal", "Geprüften Zahlungsvorschlag ansehen", path
            href = "/invoice-review?tab=proposals"
        else:
            stage, label, area = "bank_check", "Empfänger und Zahlbetrag freigeben", f"/invoices/{row.id}/payment-authorization"
            href += "#bankfreigabe"
            blockers = gate["blockers"] or ["Eine aktuelle Bankdatenfreigabe fehlt."]
            if (gate.get("recipient") or {}).get("created_by") == user["id"] and gate["policy"]["effective_mode"] == "four_eyes":
                waiting = "Eine andere berechtigte Person muss die Bankdaten gegenprüfen."
    elif any(f["code"] == "changed_after_check" for f in view["findings"]):
        stage, label, area = "recheck", "Geänderte Rechnungsdaten erneut prüfen", path + "/arithmetic-check"
        blockers = [f["message"] for f in view["findings"] if f["code"] == "changed_after_check"]
    elif not review["factual_result"] and view["kind"] != "credit_note":
        stage, label, area = "factual", "Leistung und Zuordnung prüfen", path + "/factual-check"
        blockers = ["Die sachliche Prüfung steht aus."]
    elif not review["arithmetic_result"]:
        stage, label, area = "arithmetic", "Beträge und Pflichtangaben prüfen", path + "/arithmetic-check"
        blockers = ["Die rechnerische Prüfung steht aus."]
    else:
        stage, label, area = "decision", "Rückfrage oder Freigabe entscheiden", path + "/decision"
        blockers = [f["message"] for f in view["findings"] if f["severity"] == "error"]
        if view["four_eyes"]["required"] and user["id"] in (review["factual_by"], review["arithmetic_by"]):
            waiting = "Die Rechnungsfreigabe erfordert eine andere prüfberechtigte Person."
    return _base("invoice", stage, _action(user, label, href, area, blocked=waiting), blockers, waiting=waiting,
        deadline="Fälligkeit und Skontofrist aus dem Rechnungseingang; keine automatische Bankzahlung.",
        completed=stage in ("rejected", "paid", "credit"))


def maintenance(store, row, user):
    from . import maintenance_projects as service
    rows = Rows.reading(store)
    orders = rows.find("maintenance_orders", case_id=row.id)
    links = rows.find("maintenance_order_invoices", case_id=row.id)
    protocols = rows.find("maintenance_protocols", case_id=row.id)
    packages = rows.find("maintenance_work_packages", case_id=row.id)
    blockers = service._blockers(rows, row.id, "completed")
    base = f"/maintenance/{row.id}"
    area = base
    waiting = None
    if not row.assignee:
        stage, label = "responsibility", "Zuständigkeit festlegen"
        blockers.insert(0, "Für den Schaden ist noch keine Zuständigkeit eingetragen.")
    elif not orders:
        stage, label, area = "order", "Angebot prüfen oder Auftrag anlegen", base + "/orders"
    elif any(order.status == "active" for order in orders) or any(package.status not in service.RESOLVED for package in packages):
        stage, label, area = "performance", "Leistung und Abnahme dokumentieren", base + "/protocols"
        waiting = "Ausführung beziehungsweise Abnahme des Auftrags"
    elif not any(p.finalized_at for p in protocols):
        stage, label, area = "evidence", "Abschlussnachweis finalisieren", base + "/protocols"
        blockers.append("Ein abgeschlossenes Leistungs- oder Abschlussprotokoll fehlt.")
    elif any(order.status == "completed" and order.gross_amount > 0 and not any(link.order_id == order.id for link in links) for order in orders):
        stage, label, area = "invoice", "Rechnung mit dem Auftrag verknüpfen", base + "/invoices"
        blockers.append("Für mindestens einen ausgeführten Auftrag fehlt die zugeordnete Rechnung.")
    else:
        pending = []
        for link in links:
            reviews = rows.find("invoice_reviews", invoice_id=link.invoice_id)
            if not reviews or reviews[0].status not in ("approved", "partially_approved", "rejected") or reviews[0].dispute_status == "open":
                pending.append(link.invoice_id)
        if pending:
            stage, label, area = "invoice_review", "Zugeordnete Rechnung prüfen", f"/invoices/{pending[0]}/review"
            base = f"/invoice-review/{pending[0]}"
            blockers.append("Die Entscheidung über eine zugeordnete Rechnung steht aus.")
        else:
            stage, label, area = "closure", "Abschluss dokumentieren", base + "/transition"
    return _base("damage", stage, _action(user, label, base, area), blockers, waiting=waiting,
        assignee=row.assignee, deadline="Im Schadenfall ausdrücklich gesetzte Bearbeitungsfrist.",
        completed=row.status in ("completed", "cancelled"))


def turnover_state(store, contract):
    """Return source objects and completion from the existing deposit calculation."""
    from . import deposits
    protocols = records(store, "handover_protocols", contract_id=contract.id)
    outgoing = [p for p in protocols if p.protocol_type == "move_out"]
    finalized = any(p.finalized_at for p in outgoing)
    candidates = records(store, "contracts", unit_id=contract.unit_id)
    successor = next((c for c in sorted(candidates, key=lambda c: c.start_date)
                      if c.id != contract.id and c.status == "active" and c.start_date > contract.end_date), None)
    securities = records(store, "deposits", contract_id=contract.id)
    summaries = [deposits._brief(_unit(store), deposit) for deposit in securities]
    deposit_done = (all(item["stage"] in ("closed", "settled", "released") for item in summaries) if summaries
                    else contract.deposit_amount == 0)
    completed = contract.end_date <= local_today() and finalized and successor is not None and deposit_done
    return outgoing, successor, summaries, completed


def turnover(store, row, user):
    outgoing, successor, securities, done = turnover_state(store, row)
    finalized = any(p.finalized_at for p in outgoing)
    blockers = []
    if not finalized:
        blockers.append("Das abgeschlossene Auszugsprotokoll einschließlich Zählerständen fehlt.")
    if successor is None:
        blockers.append("Ein aktiver Folgevertrag ist noch nicht zugeordnet.")
    deposit_done = all(s["stage"] in ("closed", "settled", "released") for s in securities) if securities else row.deposit_amount == 0
    if not deposit_done:
        blockers.append("Die Kautionsprüfung beziehungsweise ein Einbehalt ist noch offen.")
    waiting = None
    href = f"/contracts?focus_id={row.id}"
    area = "/contracts"
    if done:
        stage, label = "complete", "Abgeschlossenen Mietwechsel ansehen"
    elif not finalized:
        stage, label, area = "handover", "Übergabe und Zählerstände dokumentieren", "/handover-protocols"
        href = f"/handover-protocols?focus_id={outgoing[-1].id}" if outgoing else f"/handover-protocols?contract_id={row.id}&protocol_type=move_out"
        if row.end_date > local_today():
            waiting = "Vertragsende am " + row.end_date.isoformat()
    elif successor is None:
        stage, label, area = "reletting", "Neuvermietung und Folgevertrag bearbeiten", "/reletting"
        projects = [p for p in records(store, "reletting_projects", unit_id=row.unit_id) if p.status == "open"]
        href = f"/reletting/{projects[-1].id}" if projects else f"/reletting?unit_id={row.unit_id}"
    else:
        stage, label, area = "deposit", "Kaution prüfen und Einbehalte klären", "/deposits"
        href = f"/deposits?contract_id={row.id}"
    steps = [{"id": "end", "label": "Vertragsende", "done": row.end_date <= local_today(), "href": f"/contracts?focus_id={row.id}"},
             {"id": "handover", "label": "Übergabe / Zähler", "done": finalized, "href": f"/handover-protocols?contract_id={row.id}"},
             {"id": "reletting", "label": "Neuvermietung", "done": successor is not None, "href": f"/reletting?unit_id={row.unit_id}"},
             {"id": "deposit", "label": "Kautionsprüfung", "done": deposit_done, "href": f"/deposits?contract_id={row.id}"}]
    return {**_base("turnover", stage, _action(user, label, href, area), blockers, waiting=waiting,
        deadline="Dokumentiertes Vertragsende. Für Kautionsabrechnung und Neuvermietung entsteht daraus keine pauschale gesetzliche Frist.", completed=done), "steps": steps}


def invoice_pending(store, row):
    from . import invoice_review
    rows = Rows.reading(store)
    review = invoice_review.review_of(rows, row.id)
    if review is None:
        return True
    if review.status == "rejected" or (review.kind == "credit_note" and review.status == "approved"):
        return False
    if review.status in ("approved", "partially_approved"):
        settlement = invoice_review.settlements(rows, [row], local_today())[row.id]
        return settlement.payment_status != "paid" or settlement.dispute_open > 0
    return True


def enrich(store, kind, row, user, item):
    if kind == "e_invoice":
        waiting = "Lokale Belegprüfung" if row.state == "queued" else None
        label = "Prüfstatus ansehen" if waiting else "Prüfbericht und Zuordnung prüfen"
        guidance = _base("invoice", "intake_" + row.state,
            _action(user, label, item["href"], "/e-invoice-intakes"), row.blockers, waiting=waiting,
            deadline="Noch keine fachlich bestätigte Rechnung; Fälligkeit im Originalbeleg prüfen.")
    elif kind == "invoice":
        guidance = invoice(store, row, user)
    elif kind == "maintenance":
        guidance = maintenance(store, row, user)
    elif kind == "contract_end":
        guidance = turnover(store, row, user)
    elif kind == "tenant_change":
        guidance = _base("turnover", "handover", _action(user, "Protokoll und Zählerstände vervollständigen",
            item["href"], "/handover-protocols"), ["Das Übergabeprotokoll ist noch nicht abgeschlossen."],
            deadline="Im Übergabeprotokoll geplanter Übergabetag.")
    else:
        guidance = _base(kind, "open", item["actions"][0], [], assignee=item["assignee"],
            deadline="Fälligkeit des führenden Fachdatensatzes." if item["due_date"] else "Keine Frist eingetragen.")
    overdue = (local_today() - date.fromisoformat(item["due_date"])).days if item["due_date"] else None
    guidance["escalation"] = {"rule": "source_due_date", "days_overdue": max(0, overdue or 0),
        "status": "overdue" if overdue is not None and overdue > 0 else "scheduled" if overdue is not None else "undated"}
    item["workflow"] = guidance
    if guidance["next_action"]["href"] != item["href"]:
        item["actions"].insert(0, guidance["next_action"])
    return item
