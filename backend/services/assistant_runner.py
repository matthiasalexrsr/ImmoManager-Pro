"""Durable assistant work with an explicit boundary before external inference.

Queued runs are recoverable. Running runs whose lease is lost become unknown;
they are never automatically submitted to a provider a second time.
"""
from datetime import timedelta
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ..db.assistant_models import AssistantAttachmentORM as Attachment
from ..db.assistant_models import AssistantMessageORM as Message
from ..db.assistant_models import AssistantProposalORM as Proposal
from ..db.assistant_models import AssistantRunORM as Run
from . import assistant as service
from . import assistant_storage as db
from .integrations import connection_storage as dbs
from .portfolio_scope import scope_context

KIND = "assistant.run"
LEASE_SECONDS = 180
MAX_OUTPUT = 128000
ERROR_MESSAGES = {
    "authentication_required": "Bitte das KI-Konto verbinden oder die Anmeldung erneuern.",
    "client_unavailable": "Der benötigte offizielle KI-Client ist nicht verfügbar.",
    "rate_limited": "Das Nutzungskontingent ist erreicht. Später erneut versuchen oder lokale Analyse wählen.",
    "context_too_large": "Die ausgewählten Quellen sind für dieses Modell zu umfangreich. Bitte die Auswahl eingrenzen.",
    "model_unavailable": "Das gewählte Modell ist mit diesem Konto nicht verfügbar.",
    "protocol_incompatible": "Der installierte KI-Client unterstützt das benötigte Protokoll nicht.",
    "output_too_large": "Die KI-Antwort überschreitet das Verarbeitungspaket. Bitte den Ergebnisstatus prüfen und die Anfrage eingrenzen.",
    "provider_timeout": "Das Zeitlimit wurde erreicht. Bitte den externen Ergebnisstatus vor einem neuen Versuch prüfen.",
    "process_closed": "Die Verbindung zum KI-Client wurde unterbrochen. Bitte den Ergebnisstatus prüfen.",
    "process_isolation_unavailable": "Der geschützte KI-Prozess konnte nicht eingerichtet werden.",
    "credentials_unavailable": "Die geschützte Anmeldung ist nicht verfügbar. Bitte Schlüssel oder Sicherung prüfen.",
    "private_directory_unavailable": "Der private Arbeitsordner konnte nicht eingerichtet werden.",
    "provider_busy": "Dieser KI-Zugang wird bereits verwendet. Bitte den laufenden Auftrag abwarten.",
    "unsupported_provider": "Dieser KI-Anbieter wird nicht unterstützt.",
    "invalid_model": "Die Modellkennung ist ungültig.",
    "unsupported_attachment": "Dieses Anhangformat wird vom gewählten Modell nicht unterstützt.",
    "invalid_attachment": "Ein ausgewählter Anhang ist ungültig.",
    "unknown_result": "Der externe Ausgang ist unklar. Bitte vor einem neuen Versuch prüfen.",
    "empty_answer": "Der KI-Anbieter lieferte keine verwertbare Antwort.",
    "provider_error": "Der KI-Anbieter konnte den Auftrag nicht abschließen.",
    "cancelled": "Der KI-Auftrag wurde abgebrochen.",
    "invalid_response": "Der KI-Anbieter lieferte ein ungültiges Ergebnis.",
    "input_too_large": "Das Anfragepaket überschreitet die Transportgrenze des Anbieters. Bitte weniger Quellen oder Bilder auswählen; die Originale bleiben erhalten.",
    "provider_isolation_failed": "Der KI-Client hat nicht freigegebene Werkzeuge geladen. Der Lauf wurde aus Sicherheitsgründen beendet.",
    "unexpected_tool": "Der KI-Client hat ein nicht freigegebenes Werkzeug angefordert. Der Lauf wurde beendet.",
    "provider_protocol_error": "Der KI-Client lieferte ein nicht unterstütztes Antwortformat. Bitte dessen installierte Version prüfen.",
    "provider_execution_failed": "Claude konnte die Anfrage nicht abschließen. Bitte Konto, Modell und Verarbeitungshinweise prüfen.",
    "unsupported_feature": "Diese Funktion ist im ausgewählten Modus nicht verfügbar.",
    "provider_interrupted": "KI-Auftrag nicht abgeschlossen. Bitte Status prüfen und bewusst neu starten.",
}


def record_event(value, event):
    sequence = value["events"][-1]["sequence"] + 1 if value["events"] else 1
    value["events"].append({"sequence": sequence, **event})
    if len(value["events"]) > 100:
        value["event_history_truncated"] = True
        value["events"] = value["events"][-100:]


def request_history(unit, row, data, history_page, conversation):
    """Regrant every historical input; removing a file also removes its derivatives.

    Only transmission is filtered. The encrypted, owner-bound chat stays intact.
    Old runs did not record transitive input dependencies, so their provenance is
    conservatively bounded by the conversation's guards and file library.
    """
    from .assistant_tools import _permitted

    active_files = set(data["attachment_ids"])
    current_sources = {(source["kind"], source["id"]) for source in data["_bundle"]["sources"]}
    legacy_sources = {(source["kind"], source["id"]) for bundle in conversation.get("_contexts", [])
                      for source in bundle["sources"]}
    permitted = {}
    runs = {}
    legacy_excluded_file = None
    messages, budget = [], 128000
    truncated, scope_omitted, file_omitted = history_page["has_more"], False, False
    dependencies = set(current_sources)
    attachment_dependencies = set(active_files)

    for item in history_page["items"]:  # newest first; trim only older context
        text = item["content"]
        sources = {(source["kind"], source["id"]) for source in item.get("sources", [])}
        files = set(item.get("attachment_ids", []))
        prior_id = item.get("run_id")
        if prior_id == row.id:
            sources |= current_sources
            files |= active_files
        else:
            if prior_id not in runs:
                previous = db.get(unit, Run, prior_id) if prior_id else None
                if previous is not None and previous.conversation_id != row.conversation_id:
                    raise HTTPException(409, "Die Herkunft eines Gesprächsbeitrags ist nicht eindeutig.")
                runs[prior_id] = db.payload(previous) if previous is not None else {}
            previous_data = runs[prior_id]
            proof = previous_data.get("_history_inputs")
            if proof is not None:
                sources |= {(source["kind"], source["id"]) for source in proof["sources"]}
                files.update(proof["attachment_ids"])
            else:
                sources |= legacy_sources
                files.update(previous_data.get("attachment_ids", []))
                if legacy_excluded_file is None:
                    if unit.db is None:
                        legacy_excluded_file = any(attachment.owner_id == unit.actor_id
                            and attachment.conversation_id == row.conversation_id and attachment.id not in active_files
                            for attachment in dbs.memory(unit, Attachment).values())
                    else:
                        legacy_excluded_file = unit.db.scalar(select(Attachment.id).where(
                            Attachment.owner_id == unit.actor_id, Attachment.conversation_id == row.conversation_id,
                            Attachment.id.not_in(active_files)).limit(1)) is not None
                if legacy_excluded_file:
                    file_omitted = True
                    continue
                # All currently available files are selected. Their contents
                # could already be reflected in an older untracked answer.
                files |= active_files
        if not files.issubset(active_files):
            file_omitted = True
            continue
        allowed = True
        for kind, identifier in sorted(sources):
            key = (kind, identifier)
            if key not in permitted:
                try:
                    _permitted(unit, data, kind, identifier)
                    permitted[key] = True
                except HTTPException:
                    permitted[key] = False
            allowed &= permitted[key]
        if not allowed:
            scope_omitted = True
            continue
        if item["role"] == "assistant":
            text = "[Historische Modellinterpretation vom " + item["created_at"] + "; Zahlen und Quellenstände können überholt sein.]\n" + text
        if len(text) > budget:
            truncated = True
            break
        messages.append({"role": item["role"], "content": text,
                         **({"historical_sources": item.get("sources", []),
                             "historical_financial_summary": item.get("financial_summary")}
                            if item["role"] == "assistant" else {})})
        budget -= len(text)
        dependencies |= sources
        attachment_dependencies |= files
    messages.reverse()
    omissions = (["Verlauf für diesen Verarbeitungsschritt auf die letzten 60 Nachrichten / 128.000 Zeichen begrenzt. Die vollständige Historie bleibt gespeichert."]
                 if truncated else [])
    if scope_omitted:
        omissions.append("Frühere Gesprächsbeiträge mit Fachquellen außerhalb des aktuellen Datenumfangs wurden nicht erneut übertragen; sie bleiben im gespeicherten Verlauf erhalten.")
    if file_omitted:
        omissions.append("Frühere Gesprächsbeiträge mit abgewählten Arbeitsdateien oder nicht vollständig zuordenbarer Dateiquelle wurden nicht erneut übertragen; sie bleiben im gespeicherten Verlauf erhalten.")
    data["_history_inputs"] = {"sources": [{"kind": kind, "id": identifier} for kind, identifier in sorted(dependencies)],
                               "attachment_ids": sorted(attachment_dependencies)}
    return messages, omissions


def metadata_rows(store, states, limit=100):
    """Installation recovery reads metadata only; never decrypts chat content."""
    if hasattr(store, "db"):
        from sqlalchemy.orm import Session
        with scope_context(None), Session(bind=store.db.get_bind()) as session:
            return [dict(id=row.id, owner_id=row.owner_id, state=row.state, revision=row.revision,
                         updated_at=row.updated_at, conversation_id=row.conversation_id)
                    for row in session.scalars(select(Run).where(Run.state.in_(states))
                        .order_by(Run.updated_at, Run.id).limit(limit))]
    rows = store.__dict__.get("_integration_connections", {}).get(Run.__tablename__, {})
    return [dict(id=row.id, owner_id=row.owner_id, state=row.state, revision=row.revision,
                 updated_at=row.updated_at, conversation_id=row.conversation_id)
            for row in sorted(rows.values(), key=lambda row: (row.updated_at, row.id)) if row.state in states][:limit]


def metadata_block(store, identifier, owner_id, state="blocked", *, expected_revision=None):
    """Conservative worker update after revoked login; cannot make anything runnable."""
    if state not in ("unknown", "blocked"):
        raise ValueError("Only conservative outcomes may bypass actor access")
    from .document_versions import begin_writer, memory_archive
    if hasattr(store, "db"):
        from sqlalchemy import update
        from sqlalchemy.orm import Session
        with scope_context(None), Session(bind=store.db.get_bind()) as session:
            begin_writer(session)
            query = update(Run).where(Run.id == identifier, Run.owner_id == owner_id, Run.state.in_(service.ACTIVE))
            if expected_revision is not None:
                query = query.where(Run.revision == expected_revision)
            session.execute(query.values(state=state, revision=Run.revision + 1, updated_at=dbs.now()))
            session.commit()
    else:
        with memory_archive(store).lock:
            rows = store.__dict__.get("_integration_connections", {}).get(Run.__tablename__, {})
            row = rows.get(identifier)
            if row is not None and row.owner_id == owner_id and row.state in service.ACTIVE and (
                    expected_revision is None or expected_revision == row.revision):
                rows[row.id] = Run(**{**dbs.values(row), "state": state,
                    "revision": row.revision + 1, "updated_at": dbs.now()})


def recover(jobs, store=None):
    if store is None:
        from ..dependencies import store
    for row in metadata_rows(store, service.ACTIVE):
        if row["state"] == "running":
            if row["updated_at"] < dbs.now() - timedelta(seconds=LEASE_SECONDS):
                metadata_block(store, row["id"], row["owner_id"], "unknown", expected_revision=row["revision"])
            continue
        key = "assistant:" + row["id"]
        prior = jobs.find(key)
        if prior is not None and prior.status == "failed":
            # A failed infrastructure wakeup does not alter authorization or provider state.
            key += ":recovery:" + str(row["revision"])
            recovery = jobs.find(key)
            if recovery is not None and recovery.status == "failed":
                try:
                    with db.work(store, row["owner_id"], write=True) as unit:
                        current = db.owned_child(unit, Run, row["id"], lock=True)
                        if current.state != "queued" or current.revision != row["revision"]:
                            continue
                        current = db.put(unit, Run, db.payload(current), row=current)
                        key = "assistant:" + row["id"] + ":recovery:" + str(current.revision)
                except HTTPException:
                    metadata_block(store, row["id"], row["owner_id"])
                    continue
        jobs.enqueue(KIND, key, {"run_id": row["id"], "actor_id": row["owner_id"]}, max_attempts=1)


def run(store, identifier: str, actor_id: str, *, execute=None):
    from .assistant_context import local_analysis, revalidate_context
    if execute is None:
        from .assistant_providers import execute as provider_execute
        execute = provider_execute
    token = str(uuid4())
    try:
        with db.work(store, actor_id, write=True) as unit:
            row = db.owned_child(unit, Run, identifier, lock=True)
            if row.state != "queued":
                return
            data = db.payload(row)
            revalidate_context(unit.store, data["_bundle"], actor_id)
            conversation = db.conversation(unit, row.conversation_id)
            conversation_data = db.payload(conversation)
            settings = {**conversation_data, **{key: data[key] for key in ("provider", "model", "effort") if key in data}}
            service.require_demo_local(conversation_data)
            service.require_demo_local(settings)
            data.update({key: settings[key] for key in ("provider", "model", "effort")})
            # Before changing to running, all selected bytes must still match.
            attachments = [service.attachment_request(db.owned_child(unit, Attachment, item)) for item in data["attachment_ids"]]
            analysis = local_analysis(unit.store, data["context"], actor_id, report=data.get("report"), extract_documents=True)
            data["local_findings"] = analysis.get("findings", [])
            data["local_checks"] = analysis.get("checks", {})
            if analysis.get("finance") is not None:
                finance = analysis["finance"]
                data["_report_hash"] = finance["result_hash"]
                data["financial_summary"] = {key: finance[key] for key in ("kind", "currency", "basis", "filters", "totals", "result_hash", "definition") if key in finance}
                data["financial_summary"]["as_of"] = finance["definition"]["as_of"]
            history_page = db.page(unit, Message, conversation_id=row.conversation_id, limit=60)
            messages, data["omissions"] = request_history(unit, row, data, history_page, db.payload(conversation))
            data.update(_lease=token, _submitted=True)
            data["events"] = [{"sequence": 1, "type": "status", "message": "Auftrag gestartet."}]
            db.put(unit, Run, data, row=row, state="running")
            request = dict(run_id=identifier, model=settings["model"], effort=settings["effort"], messages=messages,
                           application_clock={"date": analysis["checks"]["as_of"], "timezone": "Europe/Berlin"},
                           data_scope=data.get("data_scope", "selected"),
                           web_research=data.get("web_research", False),
                           context=data["_bundle"], local_analysis=analysis, attachments=attachments,
                           omissions=data["omissions"])
            provider = settings["provider"]
    except HTTPException:
        metadata_block(store, identifier, actor_id)
        return

    last_heartbeat = monotonic()

    def cancelled():
        nonlocal last_heartbeat
        try:
            moment = monotonic()
            heartbeat = moment - last_heartbeat >= 45
            with db.work(store, actor_id, write=heartbeat) as unit:
                current = db.owned_child(unit, Run, identifier, lock=heartbeat)
                data = db.payload(current)
                if current.state != "running" or data.get("_lease") != token:
                    return True
                if heartbeat:
                    # A model can think without emitting text for several minutes.
                    # The same lease remains live, with a fresh account/source
                    # check, and no provider call or message inside this unit.
                    db.put(unit, Run, data, row=current)
                    last_heartbeat = moment
                return False
        except HTTPException:
            return True

    def emit(event):
        if event.get("type") not in ("delta", "status"):
            return
        with db.work(store, actor_id, write=True) as unit:
            current = db.owned_child(unit, Run, identifier, lock=True)
            value = db.payload(current)
            if current.state != "running" or value.get("_lease") != token:
                raise HTTPException(409, "Auftrag ist nicht mehr aktiv.")
            key = "text" if event["type"] == "delta" else "message"
            text = str(event.get(key, ""))
            for offset in range(0, len(text), 16000):
                record_event(value, {"type": event["type"], key: text[offset:offset + 16000]})
            if event["type"] == "delta":
                truncated = len(value["response"]) + len(text) > MAX_OUTPUT
                value["response"] = (value["response"] + text)[:MAX_OUTPUT]
                if truncated and not value.get("preview_truncated"):
                    value["preview_truncated"] = True
                    record_event(value, {"type": "status", "message": "Streaming-Vorschau gekürzt; maßgeblich ist die vollständige Abschlussantwort beziehungsweise der Fehlerstatus."})
            db.put(unit, Run, value, row=current)

    try:
        if provider == "local":
            result = execute(actor_id, provider, request, emit, cancelled)
        else:
            from .assistant_tool_server import application_mcp
            with application_mcp(store, actor_id, identifier, token) as connection:
                request["_application_mcp"] = connection
                result = execute(actor_id, provider, request, emit, cancelled)
        with db.work(store, actor_id, write=True) as unit:
            current = db.owned_child(unit, Run, identifier, lock=True)
            value = db.payload(current)
            if current.state != "running" or value.get("_lease") != token:
                return
            snapshot_stale = False
            try:
                revalidate_context(unit.store, value["_bundle"], actor_id)
            except HTTPException as exc:
                from .assistant_context import content_hash
                bundle = value["_bundle"]
                if exc.status_code != 409 or content_hash({key: item for key, item in bundle.items() if key != "sha256"}) != bundle["sha256"]:
                    raise
                snapshot_stale = True
            for attachment_id in value["attachment_ids"]:
                service.verified_attachment(db.owned_child(unit, Attachment, attachment_id))
            text = result.get("text", "")
            if not isinstance(text, str) or len(text) > MAX_OUTPUT:
                from .assistant_provider_protocol import ProviderError
                raise ProviderError("Ungültige Antwort", "output_too_large" if isinstance(text, str) else "invalid_response")
            value["response"] = text
            # Include reads made after request construction, without expanding
            # the original grant used to authorize this run's application tools.
            dependencies = {(source["kind"], source["id"]) for source in value["_history_inputs"]["sources"]}
            dependencies.update((source["kind"], source["id"]) for source in value["_bundle"]["sources"])
            value["_history_inputs"]["sources"] = [{"kind": kind, "id": identifier} for kind, identifier in sorted(dependencies)]
            value["verification_status"] = "stale" if snapshot_stale else "current"
            stale = snapshot_stale
            if snapshot_stale:
                value["error"] = {"code": "analysis_stale", "message": "Verwendete Akten wurden während der Recherche geändert."}
                text = "Hinweis: Verwendete Akten wurden während der Recherche geändert. Diese Antwort beschreibt den archivierten früheren Stand; bitte erneut prüfen.\n\n" + text
                value["response"] = text
            from .assistant_tools import validate_reports
            try:
                validate_reports(unit.store, value)
            except HTTPException:
                stale = True
                value["verification_status"] = "stale"
                value["error"] = {"code": "analysis_stale", "message": "Werkzeug-Auswertungen haben sich während der Analyse geändert."}
                text = "Hinweis: Verwendete Recherchegrundlagen wurden geändert. Diese Antwort beschreibt einen früheren Stand; bitte erneut prüfen.\n\n" + text
                value["response"] = text
            if value.get("report") and value.get("_report_hash"):
                from ..finance_models import ReportDefinition
                from .finance_reports import compute
                latest = compute(unit.store, ReportDefinition.model_validate(value["report"]))
                if latest["result_hash"] != value["_report_hash"]:
                    stale = True
                    value["verification_status"] = "stale"
                    value["error"] = {"code": "analysis_stale", "message": "Auswertungsdaten haben sich während der Analyse geändert."}
                    text = "Hinweis: Die Auswertungsdaten haben sich während dieser Analyse geändert. Die folgenden Zahlen beziehen sich auf den früheren, archivierten Stand und müssen erneut geprüft werden.\n\n" + text
                    value["response"] = text
            for key in ("provider_session_id", "provider_turn_id", "usage"):
                if key in result:
                    value[key] = result[key]
            candidates = [] if stale else result.get("proposals", [])
            if not isinstance(candidates, list):
                candidates = []
                record_event(value, {"type": "status", "message": "Ungültige Vorschlagsliste wurde verworfen."})
            if len(candidates) > 20:
                record_event(value, {"type": "status", "message": f"{len(candidates) - 20} weitere Anlagevorschläge wurden nicht übernommen. Bitte die Anfrage eingrenzen; maximal 20 Vorschläge pro Auftrag."})
            for proposed in candidates[:20]:
                # Preserve a reviewable candidate, never execute model-provided operations.
                from pydantic import ValidationError

                from .assistant_proposals import Proposal as ProposalModel
                try:
                    normalized = ProposalModel.model_validate(proposed).model_dump(mode="json")
                except (ValidationError, TypeError):
                    record_event(value, {"type": "status", "message": "Ein ungültiger Anlagevorschlag wurde verworfen."})
                    continue
                candidate = db.put(unit, Proposal, {"run_id": current.id, "payload": normalized,
                    "decision": None}, conversation_id=current.conversation_id, state="proposed")
                value["_proposal_ids"].append(candidate.id)
            from .assistant_findings import collected
            db.put(unit, Message, {"role": "assistant", "content": text, "run_id": current.id,
                "provider": value.get("provider", provider), "model": value.get("model"),
                "sources": service.source_cards(value["_bundle"]), "verification_status": value["verification_status"],
                "financial_summary": value.get("financial_summary"),
                "findings": collected(value), "local_checks": value.get("local_checks")},
                   conversation_id=current.conversation_id)
            current = db.put(unit, Run, value, row=current, state="completed")
            service.release_conversation(unit, current)
    except Exception as exc:
        # Never put provider exception strings (which may carry tokens or text) in the API or logs.
        code = str(getattr(exc, "code", "provider_interrupted"))
        if code not in ERROR_MESSAGES:
            code = "provider_interrupted"
        state = "unknown" if getattr(exc, "uncertain", True) else "failed"
        try:
            with db.work(store, actor_id, write=True) as unit:
                current = db.owned_child(unit, Run, identifier, lock=True)
                value = db.payload(current)
                if current.state != "running" or value.get("_lease") != token:
                    return
                value["error"] = {"code": code, "message": ERROR_MESSAGES[code]}
                # An interrupted draft response is retained but never claimed as complete.
                current = db.put(unit, Run, value, row=current, state=state)
                service.release_conversation(unit, current)
        except HTTPException:
            metadata_block(store, identifier, actor_id)


def handler(ctx):
    from ..dependencies import store
    run(store, ctx.run.payload["run_id"], ctx.run.payload["actor_id"])
    with ctx.unit() as unit:
        unit.save({"done": True}, {"state": "processed"})
    return True
