"""Verify channel evidence in a selected restore using only supplied archived keys."""

import base64
import hashlib
import json

from sqlalchemy import inspect, select

from ..db.channel_models import ChannelCaseORM, ChannelEventORM, ChannelEvidenceORM, ChannelWebhookORM


def verify_channel_restore(connection, box):
    models = (ChannelCaseORM, ChannelEvidenceORM, ChannelEventORM, ChannelWebhookORM)
    present = set(inspect(connection).get_table_names()) & {model.__tablename__ for model in models}
    if not present:
        return {"cases": 0, "originals": 0, "events": 0, "webhooks": 0}
    if len(present) != len(models):
        raise ValueError("Unvollständiges Kanalschema")

    def rows(model):
        return connection.execute(select(model.__table__).execution_options(stream_results=True, yield_per=500)).mappings()

    def opened(token, context):
        return json.loads(box.open(token, context))

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

    cases = set(connection.scalars(select(ChannelCaseORM.id)))
    originals = {}
    group = None
    sequence = 0
    size = 0
    hasher = hashlib.sha256()
    evidence_query = select(ChannelEvidenceORM.__table__).order_by(
        ChannelEvidenceORM.case_id, ChannelEvidenceORM.name, ChannelEvidenceORM.sequence)
    for row in connection.execute(evidence_query.execution_options(stream_results=True, yield_per=500)).mappings():
        if row["case_id"] not in cases:
            raise ValueError("Kanaloriginal ohne Vorgang")
        key = (row["case_id"], row["name"])
        if key != group:
            if group is not None:
                originals[group] = (size, hasher.hexdigest())
            group, sequence, size, hasher = key, 0, 0, hashlib.sha256()
        if row["sequence"] != sequence:
            raise ValueError("Kanaloriginal unvollständig")
        chunk = base64.b64decode(opened(row["data_token"], "channel-evidence/" + row["id"]), validate=True)
        if not 0 < len(chunk) <= 65536 or hashlib.sha256(chunk).hexdigest() != row["sha256"]:
            raise ValueError("Kanaloriginalblock beschädigt")
        hasher.update(chunk)
        sequence += 1
        size += len(chunk)
    if group is not None:
        originals[group] = (size, hasher.hexdigest())

    for row in rows(ChannelCaseORM):
        identifier = row['id']
        if row["entity_type"] != row["source_kind"] or row["entity_id"] != row["source_id"]:
            raise ValueError("Kanalquellbezug widersprüchlich")
        snapshot = opened(row["snapshot_token"], "channel/" + identifier + "/snapshot")
        progress = opened(row["progress_token"], "channel/" + identifier + "/progress")
        if not isinstance(snapshot, dict) or not isinstance(progress, dict):
            raise ValueError("Kanalnachweis beschädigt")
        if row["channel"] == "aktenwerk":
            source_hash = snapshot["sha256"]
        elif "inbound" in snapshot:
            source_hash = digest(snapshot)
        else:
            source_hash = digest(
                {key: value for key, value in snapshot.items() if key not in ("originals", "parameters")}
            )
        if source_hash != row["source_sha256"]:
            raise ValueError("Kanalquellhash widersprüchlich")
        manifests = [
            *snapshot.get("originals", []),
            *[
                progress.get(key)
                for key in ("purchased_original", "media_original", "received_media")
                if progress.get(key)
            ],
        ]
        for manifest in manifests:
            if originals.get((identifier, manifest["evidence_name"])) != (manifest["size"], manifest["sha256"]):
                raise ValueError("Vollständiges Kanaloriginal stimmt nicht mit dem Beleg überein")
    events = 0
    for row in rows(ChannelEventORM):
        body = opened(row["data_token"], "channel-event/" + row["id"])
        if row["case_id"] not in cases or digest(body) != row["replay_hash"]:
            raise ValueError("Kanalereignis beschädigt")
        events += 1
    webhooks = 0
    for row in rows(ChannelWebhookORM):
        raw = base64.b64decode(opened(row["raw_token"], "channel-webhook/" + row["id"]), validate=True)
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Signierter Kanalempfang beschädigt")
        if not isinstance(json.loads(raw), dict):
            raise ValueError("Kanalempfang ist kein Objekt")
        webhooks += 1
    return {"cases": len(cases), "originals": len(originals), "events": events, "webhooks": webhooks}
