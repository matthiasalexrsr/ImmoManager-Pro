"""Verify private provider-result blocks before exposing a redacted projection.

No function in this module opens a network connection or chooses credentials.
It receives an already authorized transaction and an explicit SecretBox. The
caller retains authorization responsibility for the run and its source.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from ...db.integration_connection_models import IntegrationSourceBlockORM
from . import connection_storage as storage

SENSITIVE = re.compile(r"password|passwd|secret|token|credential|authorization|api.?key|tan$|pin$", re.I)
RESULT_FORMAT = "immomanager-connection-result/2"


def invalid() -> HTTPException:
    return HTTPException(503, "Der gespeicherte Ergebnisnachweis ist unvollständig, verändert oder einem anderen Vorgang zugeordnet.")


def block_identity(block) -> dict:
    return {"id": block.id, "run_id": block.run_id, "category": block.category,
            "sequence": block.sequence, "sha256": block.sha256, "byte_length": block.byte_length,
            "created_at": storage.stamp(block.created_at)}


def encode_block(block, data: bytes, box) -> str:
    if hashlib.sha256(data).hexdigest() != block.sha256 or len(data) != block.byte_length:
        raise invalid()
    envelope = {"format": RESULT_FORMAT, "identity": block_identity(block),
                "data": base64.b64encode(data).decode("ascii")}
    return storage.seal(envelope, f"connection-block/{block.id}", box)


def decode_block(block, box, *, require_bound: bool = True) -> bytes:
    encoded = storage.unseal(block.data_token, f"connection-block/{block.id}", box)
    if isinstance(encoded, dict) and encoded.get("format") == RESULT_FORMAT:
        if encoded.get("identity") != block_identity(block):
            raise invalid()
        value = encoded.get("data")
    elif isinstance(encoded, str) and not require_bound:
        # Version-one development records are preserved, not retroactively
        # described as having a metadata-bound proof that they never had.
        value = encoded
    else:
        raise invalid()
    try:
        if not isinstance(value, str):
            raise ValueError
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise invalid() from None
    if (not 0 < len(raw) <= storage.BLOCK_BYTES or len(raw) != block.byte_length
            or hashlib.sha256(raw).hexdigest() != block.sha256):
        raise invalid()
    return raw


def _blocks(unit, run_id: str, category: str):
    if unit.db is None:
        return sorted((item for item in storage.memory(unit, IntegrationSourceBlockORM).values()
                       if item.run_id == run_id and item.category == category), key=lambda item: item.sequence)
    return unit.db.scalars(select(IntegrationSourceBlockORM).where(
        IntegrationSourceBlockORM.run_id == run_id, IntegrationSourceBlockORM.category == category)
        .order_by(IntegrationSourceBlockORM.sequence).execution_options(yield_per=32))


def result_bytes(unit, run_id: str, manifest: dict, box) -> bytes:
    """One bounded original result, verified completely before any bytes return."""
    if not isinstance(manifest, dict):
        raise invalid()
    size, count = manifest.get("bytes"), manifest.get("blocks")
    if (type(size) is not int or size < 1 or type(count) is not int or count < 1
            or count != (size + storage.BLOCK_BYTES - 1) // storage.BLOCK_BYTES
            or not isinstance(manifest.get("category"), str)
            or not isinstance(manifest.get("sha256"), str)):
        raise invalid()
    budget = getattr(storage.settings, "integration_step_max_bytes", storage.STEP_BYTES_DEFAULT)
    if size > budget:
        raise HTTPException(413, "Der gespeicherte Abschnitt überschreitet das aktuelle Arbeitsbudget. Das Budget ausdrücklich erhöhen; der Nachweis bleibt erhalten.")
    bound = manifest.get("format") == RESULT_FORMAT
    if bound and manifest.get("run_id") != run_id:
        raise invalid()
    output = bytearray()
    observed = 0
    for block in _blocks(unit, run_id, manifest["category"]):
        if block.sequence != observed or observed >= count:
            raise invalid()
        chunk = decode_block(block, box, require_bound=bound)
        if len(output) + len(chunk) > size:
            raise invalid()
        output.extend(chunk)
        observed += 1
    if observed != count or len(output) != size or hashlib.sha256(output).hexdigest() != manifest["sha256"]:
        raise invalid()
    return bytes(output)


def result_value(unit, run_id: str, manifest: dict, box) -> Any:
    try:
        return json.loads(result_bytes(unit, run_id, manifest, box))
    except (UnicodeError, ValueError, RecursionError):
        raise invalid() from None


def public_projection(value: Any, *, secrets: list[str] | tuple[str, ...] = ()) -> Any:
    """A display/export projection, never mislabeled as original provider bytes."""
    known = tuple(secret for secret in secrets if isinstance(secret, str) and secret)
    def visit(item):
        if isinstance(item, dict):
            return {visit(str(key)): "***" if SENSITIVE.search(str(key)) else visit(child) for key, child in item.items()}
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, str):
            for secret in known:
                item = item.replace(secret, "***")
            return item
        return item
    return visit(value)
