"""Keep holds and tombstones authoritative during customer migration."""
from ...db.privacy_models import PrivacyControlORM, PrivacyDecisionORM, PrivacyRequestORM
from ...privacy_models import JournalControl
from ..integrations import connection_storage as db
from .storage import control, key

MODELS = (PrivacyControlORM, PrivacyDecisionORM, PrivacyRequestORM)
ACTIVE_MODELS = (PrivacyControlORM, PrivacyRequestORM)
KINDS = {"e_invoice_intakes": "e_invoice_intake", "external_portal_cases": "portal_case",
         "external_portal_identities": "portal_identity", "documents": "document"}


def guard(unit, table, identifier):
    kind = KINDS.get(table)
    item = control(unit, kind, identifier) if kind else None
    if item and (item.erased_at or item.erasure_due):
        raise ValueError("Ein gelöschter oder zur Löschung vorgemerkter Datensatz darf nicht erneut importiert werden: " + table + " " + identifier)


def validate(active, final):
    objects = {(model.__tablename__, value["id"]): value for model, value, _ in active}
    for model, value, _ in active:
        if model is PrivacyControlORM:
            parsed = JournalControl.model_validate(value)
            if parsed.id != key(parsed.kind, parsed.record_id) or (parsed.erased_at and not parsed.restricted):
                raise ValueError("Ungültige Datenschutzentscheidung im Kundenexport.")
            if parsed.erased_at or parsed.erasure_due:
                table = next((table for table, kind in KINDS.items() if kind == parsed.kind), None)
                preserved_shell = objects.get((table, parsed.record_id)) if table else None
                safe_shell = bool(parsed.kind == "portal_identity" and preserved_shell and not preserved_shell["active"]
                    and preserved_shell["password_hash"] is None and preserved_shell["email"].startswith("erased-"))
                if parsed.kind == "portal_case" and preserved_shell and not preserved_shell["active"]:
                    safe_shell = not any(value.get("case_link_id") == parsed.record_id for (name, _), value in objects.items() if name == "external_portal_messages")
                if table and not safe_shell and ((table, parsed.record_id) in objects or parsed.record_id in final.get(table, {})):
                    raise ValueError("Der Kundenexport würde eine vorgemerkte oder bereits ausgeführte Löschung rückgängig machen.")
        if model is PrivacyRequestORM:
            table = "tenants" if value["subject_kind"] == "tenant" else "contacts" if value["subject_kind"] == "contact" else None
            if not table or value["subject_id"] not in final.get(table, {}) or value["request_type"] not in ("access", "erasure"):
                raise ValueError("Datenschutzanfrage ohne überprüfbare Partei.")


def restored(model, value, actor_id, batch_id):
    if model is PrivacyRequestORM:
        # A transferred decision is evidence; new controllers must review it.
        return {**value, "state": "open", "revision": value["revision"] + 1,
            "created_by": actor_id, "idempotency_key": "import-" + batch_id + "-" + value["id"], "updated_at": db.now()}
    return value
