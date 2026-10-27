"""Small deterministic checks over disclosed facts; no inferred payments or writes."""
from datetime import date

CHECKS = ("deadlines", "missing_data", "consistency", "invoice_arithmetic", "invoice_payments")
KINDS = ("task", "invoice", "contract", "receivable", "unit", "document")


def evidence(source: dict) -> dict:
    return {key: source[key] for key in ("kind", "id", "revision", "sha256", "title", "href")}


def finding(source: dict, code: str, message: str, *, severity="review", next_step=None) -> dict:
    from .assistant_context import content_hash
    result = {"code": code, "severity": severity, "message": message, "evidence": [evidence(source)]}
    result["id"] = content_hash({"code": code, "evidence": [
        {key: source[key] for key in ("kind", "id", "revision", "sha256")}]})
    if next_step:
        result["next_step"] = next_step
    return result


def findings_for_source(source: dict, as_of: date, checks=None) -> list[dict]:
    """Checks describe recorded status, never invent absent tasks or bank settlement."""
    checks = set(CHECKS if checks is None else checks)
    kind, values = source["kind"], source["values"]
    status = values.get("status")
    found = []

    def add(code, message, **kwargs):
        found.append({**finding(source, code, message, **kwargs), "as_of": as_of.isoformat()})

    due = values.get("due_date")
    active_task = kind == "task" and status not in ("completed", "cancelled", "done")
    if "deadlines" in checks:
        if active_task and due and str(due)[:10] < as_of.isoformat():
            add("task_overdue", "Die Aufgabe ist laut erfasstem Status noch offen und ihr Termin liegt vor dem Prüftag.",
                next_step="Bearbeitungsstand prüfen und Aufgabe bei Bedarf abschließen oder neu terminieren.")
        if kind == "invoice" and status not in ("paid", "cancelled", "rejected") and due and str(due)[:10] < as_of.isoformat():
            add("invoice_recorded_overdue", "Die Rechnungsfrist ist überschritten; der erfasste Status lautet weder bezahlt noch storniert oder abgelehnt. Der Status allein beweist keinen offenen Zahlungsbetrag.",
                next_step="Zahlungszuordnung und Rechnungsprüfung abgleichen.")
        if kind == "receivable" and status in ("open", "partial", "partially_paid", "overdue") and due and str(due)[:10] < as_of.isoformat():
            add("receivable_recorded_overdue", "Die Forderung ist laut erfasstem Status offen und vor dem Prüftag fällig. Eine tatsächliche Restschuld ist damit noch nicht berechnet.",
                next_step="Forderung mit dem Mietkonto und den zugeordneten Zahlungen abgleichen.")
    if "missing_data" in checks:
        if active_task and not due:
            add("task_due_missing", "Für die offene Aufgabe ist kein Fälligkeitstermin erfasst.",
                next_step="Prüfen, ob ein Termin benötigt wird.")
        if kind == "invoice" and status not in ("paid", "cancelled", "rejected") and not due:
            add("invoice_due_missing", "Für diese Rechnung ist in der Fachakte kein Fälligkeitstermin erfasst; die Rechnungsprüfung kann eigene Zahlungsbedingungen enthalten.",
                next_step="Zahlungsbedingungen in Originalbeleg und Rechnungsprüfung prüfen.")
        if kind == "unit" and values.get("area_sqm") is None:
            add("unit_area_missing", "Für diese Einheit ist keine Fläche erfasst.")
        if kind == "document" and not any(values.get(key) for key in ("property_id", "unit_id", "contract_id", "tenant_id")):
            add("document_unassigned", "Das Dokument hat keinen Immobilien-, Einheiten-, Vertrags- oder Parteienbezug.")
    if "consistency" in checks and kind == "contract":
        start, end = values.get("start_date"), values.get("end_date")
        if start and end and str(end)[:10] < str(start)[:10]:
            add("contract_dates_inconsistent", "Das Vertragsende liegt vor dem Vertragsbeginn.", severity="error")
        if status == "active" and end and str(end)[:10] < as_of.isoformat():
            add("contract_active_after_end", "Der Vertrag hat den Status aktiv, obwohl sein erfasstes Ende vor dem Prüftag liegt.",
                next_step="Verlängerung, Enddatum und Vertragsstatus prüfen.")
        if status == "expired" and end and str(end)[:10] >= as_of.isoformat():
            add("contract_expired_before_end", "Der Vertrag ist als abgelaufen erfasst, obwohl sein Enddatum am oder nach dem Prüftag liegt.")
    return found
