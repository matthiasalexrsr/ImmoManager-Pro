"""Archived-key channel verification rejects damaged isolated restore copies."""

import base64
import hashlib
import json
from datetime import datetime
from typing import cast

import pytest
from sqlalchemy import Table, create_engine, insert

from backend.db.channel_models import (
    ChannelCaseORM as Case,
)
from backend.db.channel_models import (
    ChannelEventORM as Event,
)
from backend.db.channel_models import (
    ChannelEvidenceORM as Evidence,
)
from backend.db.channel_models import (
    ChannelWebhookORM as Webhook,
)
from backend.services.channel_restore import verify_channel_restore
from backend.services.secret_box import SecretBox, SecretError


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.mark.parametrize("damage", [None, "snapshot", "progress", "block", "manifest", "event", "webhook"])
def test_restore_checks_every_encrypted_channel_original_and_receipt(tmp_path, damage):
    engine = create_engine("sqlite:///" + (tmp_path / "restore.sqlite").as_posix())
    box = SecretBox(tmp_path / "archived-keyring.json")

    def seal(value, context):
        return box.seal(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")), context)

    source = {"context": {"entity_id": "document-1", "portfolio_ids": ["portfolio-1"]}, "assets": []}
    raw = b"%PDF-1.7\nARCHIVED EXACT ORIGINAL\x00\xff"
    sha = hashlib.sha256(raw).hexdigest()
    manifest = {"evidence_name": "original-" + sha, "size": len(raw), "sha256": sha}
    frozen = {**source, "originals": [manifest], "parameters": {"recipient_name": "Synthetisch"}}
    if damage == "manifest":
        manifest["sha256"] = "0" * 64
    snapshot = seal(frozen, "channel/case-1/snapshot")
    progress = seal({"delivery_confirmed": False}, "channel/case-1/progress")
    block = seal(base64.b64encode(raw).decode(), "channel-evidence/block-1")
    event = {"state": "prepared"}
    event_token = seal(event, "channel-event/event-1")
    webhook = b'{"object":"whatsapp_business_account","entry":[]}'
    webhook_token = seal(base64.b64encode(webhook).decode(), "channel-webhook/webhook-1")
    if damage == "snapshot":
        snapshot += "corrupt"
    if damage == "progress":
        progress += "corrupt"
    if damage == "block":
        block += "corrupt"
    if damage == "event":
        event_token += "corrupt"
    if damage == "webhook":
        webhook_token += "corrupt"
    with engine.begin() as connection:
        # These isolated fixture tables deliberately have no business rows; the
        # verifier checks archive contents without loading the runtime or auth.
        for model in (Case, Evidence, Event, Webhook):
            cast(Table, model.__table__).create(connection)
        connection.execute(
            insert(Case).values(
                id="case-1",
                channel="post",
                entity_type="document",
                entity_id="document-1",
                source_kind="document",
                source_id="document-1",
                created_by="actor-1",
                revision=1,
                state="prepared",
                source_sha256=digest(source),
                snapshot_token=snapshot,
                progress_token=progress,
                created_at=datetime(2026, 10, 16),
                updated_at=datetime(2026, 10, 16),
            )
        )
        connection.execute(
            insert(Evidence).values(
                id="block-1", case_id="case-1", name="original-" + sha, sequence=0, sha256=sha, data_token=block
            )
        )
        connection.execute(
            insert(Event).values(
                id="event-1",
                case_id="case-1",
                replay_hash=digest(event),
                data_token=event_token,
                created_at=datetime(2026, 10, 16),
            )
        )
        connection.execute(
            insert(Webhook).values(
                id="webhook-1",
                connection_id="connection-1",
                sha256=hashlib.sha256(webhook).hexdigest(),
                raw_token=webhook_token,
                created_at=datetime(2026, 10, 16),
            )
        )
        if damage:
            with pytest.raises((ValueError, SecretError)):
                verify_channel_restore(connection, box)
        else:
            assert verify_channel_restore(connection, box) == {"cases": 1, "originals": 1, "events": 1, "webhooks": 1}
    engine.dispose()
