"""Evidence-bound local findings and explicit preparation through existing drafts."""
from fastapi import HTTPException

from . import assistant_context as context
from . import assistant_storage as db


def normalize(findings):
    result = {}
    for finding in findings:
        value = dict(finding)
        value["id"] = context.content_hash({"code": value["code"], "evidence": [
            {key: source[key] for key in ("kind", "id", "revision", "sha256")}
            for source in value.get("evidence", [])]})
        result[value["id"]] = value
    return list(result.values())


def collected(data):
    return normalize([*[{"as_of": data.get("local_checks", {}).get("as_of"), **finding}
                        for finding in data.get("local_findings", [])], *[
        {"as_of": activity.get("as_of"), **finding} for activity in data.get("activity", []) if activity.get("status") == "completed"
        for finding in activity.get("findings", [])]])


def prepare_task(store, actor_id, run_id, finding_id, command):
    from . import assistant as service
    from .assistant_proposals import validate_proposal
    from .assistant_tools import _permitted, merge_bundle
    operation = "finding.task:" + run_id + ":" + finding_id
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        run = db.owned_child(unit, service.Run, run_id, lock=True)
        data = db.payload(run)
        # Even replayed preparations cannot bypass newly revoked task rights.
        from . import workspace_contexts
        workspace_contexts.check_context(actor_id, "tasks", edit=True)
        replay_id = db.replay(unit, operation, command)
        previous = replay_id or data.get("finding_proposals", {}).get(finding_id)
        if previous:
            proposal = db.owned_child(unit, service.Proposal, previous)
            if not replay_id:
                db.receipt(unit, operation, command, proposal)
            return {"proposal": db.public(proposal), "run": service.run_public(unit, run)}
        db.revision(run, command.expected_revision)
        if run.state != "completed":
            raise HTTPException(409, "Bitte zuerst den Abschluss der Prüfung abwarten.")
        service.require_current_analysis(unit, run)
        finding = next((item for item in collected(data) if item["id"] == finding_id), None)
        if finding is None or not finding.get("evidence"):
            raise HTTPException(404, "Dieser belegte Prüfhinweis ist nicht verfügbar.")
        evidence, sources = [], []
        for original in finding["evidence"]:
            current = _permitted(unit, data, original["kind"], original["id"])
            if any(current[key] != original[key] for key in ("revision", "sha256")):
                raise HTTPException(409, "Der Prüfhinweis wurde durch geänderte Quellen überholt. Bitte erneut prüfen.")
            sources.append(current)
        anchor = sources[0]
        # A reminder about an existing overdue task should be handled there,
        # rather than silently creating another identical task.
        if any(source["kind"] == "task" for source in sources):
            raise HTTPException(422, "Bitte die vorhandene Aufgabe direkt öffnen und bearbeiten.")
        values = {"title": ("Klärung: " + anchor.get("title", "Prüfhinweis"))[:200],
                  "description": finding["message"] + "\n\n" + finding.get("next_step", "Angaben anhand der Originalakte prüfen.") +
                  "\n\nPrüfgrundlage: " + str(finding.get("as_of") or data.get("local_checks", {}).get("as_of") or run.created_at.date()) +
                  "\nQuelle: " + anchor.get("href", anchor["id"]), "priority": "medium", "status": "open"}
        for key, kind in (("property_id", "property"), ("unit_id", "unit")):
            identifier = anchor["id"] if anchor["kind"] == kind else anchor["values"].get(key)
            if identifier:
                sources.append(_permitted(unit, data, kind, identifier))
                values[key] = identifier
        sources = list({(source["kind"], source["id"]): source for source in sources}.values())
        evidence = [{key: source[key] for key in ("kind", "id", "revision", "sha256")} for source in sources]
        bundle = merge_bundle(data["_bundle"], sources)
        proposed = {"kind": "task", "values": values, "anchor": {"kind": anchor["kind"], "id": anchor["id"]},
                    "evidence": evidence}
        normalized = validate_proposal(unit.store, proposed, actor_id, context_bundle=bundle)["normalized"]
        proposal = db.put(unit, service.Proposal, {"run_id": run_id, "payload": normalized, "decision": None,
                         "origin": "local_finding", "finding_id": finding_id}, conversation_id=run.conversation_id, state="proposed")
        data["_bundle"] = bundle
        data.setdefault("_proposal_ids", []).append(proposal.id)
        data.setdefault("finding_proposals", {})[finding_id] = proposal.id
        run = db.put(unit, service.Run, data, row=run)
        db.receipt(unit, operation, command, proposal)
        return {"proposal": db.public(proposal), "run": service.run_public(unit, run)}
