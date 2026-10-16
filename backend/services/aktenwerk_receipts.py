"""Durable exact-id/exact-byte Aktenwerk send fence shared by API and batch handoff."""

from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from ..db.channel_models import ChannelCaseORM as Case
from . import channel_workflows as flow
from .integrations import connection_storage as db


def begin(store, actor, entry, config, content, info):
    if store is None:
        return None, None
    source_kind = entry.source.get("type")
    if source_kind not in ("document", "booking"):
        raise HTTPException(422, "Aktenwerk-Quelle benötigt eine belegbare Dokument-/Buchungskennung.")
    source_id = entry.source["id"]
    identifier = str(uuid5(NAMESPACE_URL, "aktenwerk:" + config["base_url"].rstrip("/") + ":" + entry.exchange_id))
    with flow.work(store, actor, "/aktenwerk") as unit:
        flow.resolve_context(unit.store, source_kind, source_id, actor)
        case = db.row(unit, Case, identifier, lock=True, required=False)
        if case is not None:
            flow.context(unit, case)
            frozen = flow.snapshot(case)
            if frozen["sha256"] != info["sha256"]:
                return identifier, {
                    "exchange_id": entry.exchange_id,
                    "status": "conflict",
                    "sha256": info["sha256"],
                    "reason": "Die Quelle weicht vom bereits eingefrorenen Original ab. Neue Dokumentfassung verwenden.",
                    "retry_automatically": False,
                }
            flow.read_bytes(unit, case, frozen["originals"][0])
            if case.state in ("sent", "already_present"):
                return identifier, {**flow.progress(case), "status": "already_present"}
            if case.state in ("unknown", "conflict"):
                return identifier, {**flow.progress(case), "status": case.state}
            case = flow.update(
                unit,
                case,
                state="unknown",
                details={
                    "exchange_id": entry.exchange_id,
                    "status": "unknown",
                    "sha256": info["sha256"],
                    "reason": "Ausgang der Übergabe noch nicht bestätigt.",
                    "retry_automatically": False,
                },
            )
        else:
            data = {
                "id": identifier,
                "channel": "aktenwerk",
                "source_kind": source_kind,
                "source_id": source_id,
                "entity_type": source_kind,
                "entity_id": source_id,
                "created_by": actor,
                "revision": 1,
                "state": "unknown",
                "source_sha256": info["sha256"],
                "snapshot_token": db.seal({}, "channel/" + identifier + "/snapshot"),
                "progress_token": db.seal(
                    {
                        "exchange_id": entry.exchange_id,
                        "status": "unknown",
                        "sha256": info["sha256"],
                        "reason": "Ausgang der Übergabe noch nicht bestätigt.",
                        "retry_automatically": False,
                    },
                    "channel/" + identifier + "/progress",
                ),
                "created_at": db.now(),
                "updated_at": db.now(),
            }
            case = db.put(unit, Case, data)
            manifest = flow.save_bytes(unit, case, "original", content)
            data = db.values(case)
            data["snapshot_token"] = db.seal(
                {"sha256": info["sha256"], "metadata": entry.as_manifest(info), "originals": [manifest]},
                "channel/" + identifier + "/snapshot",
            )
            case = db.put(unit, Case, data)
        flow.event(
            unit,
            case,
            {
                "action": "send_started",
                "exchange_id": entry.exchange_id,
                "sha256": info["sha256"],
                "revision": case.revision,
            },
        )
    return identifier, None


def finish(store, actor, identifier, result):
    if identifier is None:
        return
    with flow.work(store, actor, "/aktenwerk") as unit:
        case = flow.require_case(unit, identifier)
        case = flow.update(unit, case, state=result["status"], details=result, external_id=result.get("aktenwerk_id"))
        flow.event(unit, case, {"result": result, "revision": case.revision})
