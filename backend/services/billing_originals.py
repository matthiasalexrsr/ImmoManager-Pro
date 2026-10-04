"""Pure original settlement states and unchanged canonical snapshot bytes."""

import hashlib
import json

IMMUTABLE = {"finalized", "delivered", "disputed", "corrected"}


def snapshot_hash(statements: list, owner_cost_share=None) -> str:
    payload = [{key: value for key, value in s.model_dump(mode="json").items()
        if key not in {"status", "snapshot_hash", "delivery_status", "delivered_at", "delivery_channel", "updated_at"}}
        for s in sorted(statements, key=lambda s: s.id)]
    return hashlib.sha256(json.dumps({"statements": payload, "owner_cost_share": owner_cost_share},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
