"""Value-free, complete JSON shape observation and private snapshot copying.

No HTTP, files, logging, sample cutoff or inference of additional endpoints.
Field names themselves can be private (for example dynamic identifier keys);
observations still require authorized storage and disclosure.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

SCHEMA_OBSERVATION_VERSION = 1
PROFILE_SECRET_POLICY_VERSION = 1
_SECRET_NAMES = frozenset({
    "accesstoken", "refreshtoken", "idtoken", "token", "tokens", "authtoken", "bearertoken", "jwt", "jwttoken",
    "sessiontoken", "csrftoken", "xsrftoken", "password", "passwordhash", "passwd", "pwd", "passphrase", "pin",
    "secret", "secrets", "secretkey", "secretkeys", "sharedkey", "encryptionkey", "signingkey", "masterkey",
    "clientsecret", "apikey", "accesskey", "privatekey", "credential", "credentials", "authorization",
    "authheader", "cookie", "cookies", "setcookie", "sessionid",
})
_SECRET_SUFFIXES = ("token", "password", "passwordhash", "secret", "secrets", "secretkey", "secretkeys",
                    "sharedkey", "encryptionkey", "signingkey", "apikey", "privatekey", "credentials")


class SchemaObservationError(ValueError):
    """Only constant codes; invalid source values never enter error text."""


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        if not math.isfinite(value):
            raise SchemaObservationError("non_finite_json_number")
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise SchemaObservationError("non_json_value")


def is_profile_secret_key(key: str) -> bool:
    """Versioned conservative key policy; no claim to classify arbitrary text."""
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in _SECRET_NAMES or normalized.endswith(_SECRET_SUFFIXES)


def _snapshot(value: Any, *, strip_secrets: bool, secret_values: frozenset[str]) -> Any:
    # Explicit enter/exit frames detect only ancestor cycles, not legitimate
    # repeated aliases. Each occurrence receives a separate independent copy.
    holder: list[Any] = []
    pending: list[tuple[bool, Any, Any, Any]] = [(False, value, holder, None)]
    active: set[int] = set()
    while pending:
        exiting, source, parent, key = pending.pop()
        if exiting:
            active.remove(id(source))
            continue
        kind = _kind(source)
        if strip_secrets and kind == "string" and source in secret_values:
            continue
        copied: Any
        if kind in {"object", "array"}:
            if id(source) in active:
                raise SchemaObservationError("cyclic_json_value")
            active.add(id(source))
            copied = {} if kind == "object" else []
            pending.append((True, source, None, None))
            if kind == "object":
                for child_key, child in reversed(list(source.items())):
                    if not isinstance(child_key, str):
                        raise SchemaObservationError("non_string_json_key")
                    if not strip_secrets or not is_profile_secret_key(child_key):
                        pending.append((False, child, copied, child_key))
            else:
                pending.extend((False, child, copied, None) for child in reversed(source))
        else:
            copied = source
        if isinstance(parent, dict):
            parent[key] = copied
        else:
            parent.append(copied)
    return holder[0] if holder else None


def json_snapshot(value: Any) -> Any:
    """Deep independent JSON copy without Python recursion or source mutation."""
    return _snapshot(value, strip_secrets=False, secret_values=frozenset())


def private_profile_snapshot(value: dict[str, Any], *, known_secret_values: tuple[str, ...] = ()) -> dict[str, Any]:
    """Copy nonsecret profile/role/unknown values for authorized private use.

    Secret-named branches and exact aliases of known password/session values
    are omitted recursively, including array members. No public export or
    storage authorization is implied; persist only with explicit scope and
    appropriate encryption. Names/types can be observed separately beforehand.
    """
    if not isinstance(value, dict):
        raise SchemaObservationError("profile_must_be_object")
    return _snapshot(value, strip_secrets=True, secret_values=frozenset(v for v in known_secret_values if v))


_Path = tuple[str, ...]
_Key = tuple[_Path, tuple[int, ...]]


@dataclass
class _Field:
    type_occurrences: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, count: int = 1) -> None:
        self.type_occurrences[kind] = self.type_occurrences.get(kind, 0) + count


class JsonSchemaObserver:
    """Aggregate every JSON occurrence without retaining any scalar value.

    Array positions normalize to the JSON Pointer token ``0``. The separate
    array_positions list (zero-based token offsets) distinguishes real object
    key "0" from an array element. Thus these are schema patterns, not claims
    that dereferencing the first row reveals every observed field.
    """

    def __init__(self) -> None:
        self._fields: dict[_Key, _Field] = {}
        self._observations = 0

    def __repr__(self) -> str:
        return f"<JsonSchemaObserver observations={self._observations} fields={len(self._fields)}>"

    def observe(self, value: Any) -> JsonSchemaObserver:
        # Build this observation privately and merge only after full validation.
        # A malformed/cyclic late entry never changes prior accepted statistics.
        found: dict[_Key, _Field] = {}
        pending: list[tuple[bool, Any, _Path, tuple[int, ...]]] = [(False, value, (), ())]
        active: set[int] = set()
        while pending:
            exiting, current, path, array_positions = pending.pop()
            if exiting:
                active.remove(id(current))
                continue
            kind = _kind(current)
            found.setdefault((path, array_positions), _Field()).add(kind)
            if kind not in {"object", "array"}:
                continue
            if id(current) in active:
                raise SchemaObservationError("cyclic_json_value")
            active.add(id(current))
            pending.append((True, current, path, array_positions))
            if kind == "object":
                for key, child in reversed(list(current.items())):
                    if not isinstance(key, str):
                        raise SchemaObservationError("non_string_json_key")
                    pending.append((False, child, (*path, key), array_positions))
            else:
                positions = (*array_positions, len(path))
                pending.extend((False, child, (*path, "0"), positions) for child in reversed(current))
        self._merge(found)
        self._observations += 1
        return self

    def _merge(self, fields: dict[_Key, _Field]) -> None:
        for key, observed in fields.items():
            current = self._fields.setdefault(key, _Field())
            for kind, count in observed.type_occurrences.items():
                current.add(kind, count)

    def merge(self, other: JsonSchemaObserver) -> JsonSchemaObserver:
        """Merge independently observed batches; neither report stores values."""
        # Snapshot also makes merging self deterministic.
        fields = {key: _Field(dict(value.type_occurrences)) for key, value in other._fields.items()}
        self._merge(fields)
        self._observations += other._observations
        return self

    def report(self) -> dict[str, Any]:
        rows = []
        for (path, positions), observed in sorted(self._fields.items()):
            count = sum(observed.type_occurrences.values())
            parent_count = None
            if path and len(path) - 1 not in positions:
                parent = self._fields[(path[:-1], positions)]
                parent_count = parent.type_occurrences.get("object", 0)
            rows.append({
                "pointer": "".join("/" + token.replace("~", "~0").replace("/", "~1") for token in path),
                "array_positions": list(positions),
                "types": sorted(observed.type_occurrences),
                "type_occurrences": dict(sorted(observed.type_occurrences.items())),
                "occurrences": count,
                "null_occurrences": observed.type_occurrences.get("null", 0),
                "nullable_observed": "null" in observed.type_occurrences,
                "object_parent_occurrences": parent_count,
                "missing_in_objects": None if parent_count is None else parent_count - count,
            })
        return {"version": SCHEMA_OBSERVATION_VERSION, "observations": self._observations,
                "array_normalization": "zero_token_with_array_positions", "fields": rows}
