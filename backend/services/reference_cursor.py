"""Signed, scope/filter-bound keyset position; never an authorization grant."""

import base64
import hashlib
import hmac
import json
from time import time

from fastapi import HTTPException

from ..config import settings


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value):
    if not value or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in value):
        raise ValueError
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64(raw) != value:
        raise ValueError
    return raw


def _signature(payload):
    return hmac.new(settings.jwt_secret_key.encode(), b"immo-reference-cursor-v1\0" + payload, hashlib.sha256).digest()


def pack_reference_cursor(binding, identifier):
    issued = int(time())
    payload = _json({"version": 1, "binding": hashlib.sha256(_json(binding)).hexdigest(), "id": identifier,
                     "issued": issued, "expires": issued + settings.workflow_reference_cursor_seconds})
    return _b64(payload) + "." + _b64(_signature(payload))


def unpack_reference_cursor(cursor, binding):
    if cursor is None:
        return None
    try:
        left, right = cursor.split(".")
        payload = _unb64(left)
        if not hmac.compare_digest(_unb64(right), _signature(payload)):
            raise ValueError
        value = json.loads(payload)
        if set(value) != {"version", "binding", "id", "issued", "expires"} or type(value["version"]) is not int or value["version"] != 1:
            raise ValueError
        if type(value["issued"]) is not int or type(value["expires"]) is not int or value["issued"] > time() + 60 or time() >= value["expires"]:
            raise ValueError
        if not isinstance(value["binding"], str) or not hmac.compare_digest(value["binding"], hashlib.sha256(_json(binding)).hexdigest()):
            raise ValueError
        if not isinstance(value["id"], str) or not value["id"]:
            raise ValueError
        return value["id"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(422, "Die Auswahlseite ist ungültig oder abgelaufen. Bitte die erste Seite neu laden.") from None
