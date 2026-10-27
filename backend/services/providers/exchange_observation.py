"""Explicit private, complete JSON exchange observation without I/O or history.

The shape report observes all fields before secret removal. Values leave this
object only through private_snapshot(); the repr never prints identifiers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .schema_observation import JsonSchemaObserver, is_profile_secret_key, json_snapshot

EXCHANGE_OBSERVATION_VERSION = 1
EXCHANGE_SECRET_POLICY_VERSION = 1
EXCHANGE_HEADER_POLICY_VERSION = 1

# Unknown header names/types remain discoverable, but their values are not
# retained. Authentication/challenge/cookie values are never allowlisted.
_VALUE_HEADERS = frozenset({
    "accept", "accept-encoding", "cache-control", "content-encoding", "content-language",
    "content-length", "content-type", "date", "etag", "expires", "last-modified",
    "pragma", "retry-after", "server", "vary",
})
_EXTRA_SECRET_NAMES = frozenset({
    "proxyauthorization", "authentication", "cookievalue", "cookievalues", "sessioncookie", "sessioncookies",
    "setcookie2", "bearer", "bearertokens", "accesstokens", "refreshtokens", "passwords", "passwordhashes",
})


def _secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return is_profile_secret_key(key) or normalized in _EXTRA_SECRET_NAMES or normalized.endswith(
        ("authorization", "cookie", "cookies", "cookievalue", "passwords", "passwordhashes", "tokens"))


def _secret_literals(value: Any, known: Iterable[str]) -> frozenset[str]:
    """Include aliases of string values under secret-named branches, not keys."""
    values = {item for item in known if isinstance(item, str) and item}
    pending = [(value, False)]
    while pending:
        current, secret_branch = pending.pop()
        if isinstance(current, dict):
            pending.extend((child, secret_branch or _secret_key(key)) for key, child in current.items())
        elif isinstance(current, list):
            pending.extend((child, secret_branch) for child in current)
        elif secret_branch and isinstance(current, str) and current:
            values.add(current)
    return frozenset(values)


def _contains_secret(value: str, secrets: frozenset[str]) -> bool:
    return any(secret in value for secret in secrets)


def _private_copy(value: Any, secrets: frozenset[str]) -> Any:
    # Callers first validate with JsonSchemaObserver; the iterative copy then
    # omits whole strings/branches containing a known literal, even in free text.
    holder: list[Any] = []
    pending: list[tuple[Any, Any, str | None]] = [(value, holder, None)]
    while pending:
        source, parent, key = pending.pop()
        if isinstance(source, str) and _contains_secret(source, secrets):
            continue
        if isinstance(source, dict):
            copied: Any = {}
            pending.extend((child, copied, child_key) for child_key, child in reversed(list(source.items()))
                           if not _secret_key(child_key) and not _contains_secret(child_key, secrets))
        elif isinstance(source, list):
            copied = []
            pending.extend((child, copied, None) for child in reversed(source))
        else:
            copied = source
        if isinstance(parent, dict):
            parent[key] = copied
        else:
            parent.append(copied)
    return holder[0] if holder else None


def private_json_values(value: Any, *, known_secret_values: Iterable[str] = ()) -> Any:
    """Conservative private copy; secret keys and known embedded aliases omitted.

    This is no permission to persist/export. Short secret literals deliberately
    over-redact matching text. Unknown arbitrary secrets cannot be inferred.
    """
    JsonSchemaObserver().observe(value)  # Validate fully before the copy walk.
    return _private_copy(value, _secret_literals(value, known_secret_values))


def _redact_schema(report: dict[str, Any], secrets: frozenset[str]) -> dict[str, Any]:
    for entry in report["fields"]:
        pointer = entry["pointer"]
        # The observer's fixed wrapper is not a source-provided dynamic key.
        # Keep it stable even for a short password such as "body", so a
        # response-only projection never silently loses the complete schema.
        prefix = next((value for value in ("/request/body", "/request/query", "/request/headers",
                       "/response/body", "/response/headers")
                       if pointer == value or pointer.startswith(value + "/")), None)
        if prefix is None:
            continue
        suffix = pointer[len(prefix):]
        # Pointer escaping can alter a secret containing '/' or '~'.
        for secret in sorted(secrets, key=len, reverse=True):
            suffix = suffix.replace(secret.replace("~", "~0").replace("/", "~1"), "[redacted]")
        entry["pointer"] = prefix + suffix
    return report


def _headers(items: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, value in items:
        result.setdefault(name.lower(), []).append(value)
    return result


def _query(items: Iterable[Iterable[str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, value in items:
        result.setdefault(name, []).append(value)
    return result


@dataclass(frozen=True, repr=False)
class PrivateJsonExchange:
    """Sanitized semantic JSON snapshot, not original HTTP bytes or a receipt."""

    _snapshot: dict[str, Any] = field(repr=False)
    _schema: dict[str, Any] = field(repr=False)

    def __repr__(self) -> str:
        return "<PrivateJsonExchange private provider observation>"

    def private_snapshot(self) -> dict[str, Any]:
        """Explicit private access; host must authorize/encrypt any persistence."""
        return json_snapshot(self._snapshot)

    def private_schema_snapshot(self) -> dict[str, Any]:
        """Names/types only; dynamic field names can themselves be private."""
        return json_snapshot(self._schema)

    def independent_copy(self) -> PrivateJsonExchange:
        """Isolate a caller-owned sink from the transport's latest observation."""
        return PrivateJsonExchange(self.private_snapshot(), self.private_schema_snapshot())

    def private_response_snapshot(self) -> Any:
        """Sanitized whole envelope for subsequent DTO sources, never raw auth."""
        return json_snapshot(self._snapshot["response"].get("body"))

    def private_response_schema_snapshot(self) -> dict[str, Any]:
        """Response-only shape with the identical full-exchange secret policy."""
        report = self.private_schema_snapshot()
        prefix = "/response/body"
        rows = []
        for entry in report["fields"]:
            pointer = entry["pointer"]
            if pointer != prefix and not pointer.startswith(prefix + "/"):
                continue
            entry["pointer"] = pointer[len(prefix):]
            entry["array_positions"] = [position - 2 for position in entry["array_positions"]]
            if not entry["pointer"]:
                entry["object_parent_occurrences"] = None
                entry["missing_in_objects"] = None
            rows.append(entry)
        report["fields"] = rows
        return report


def observe_json_exchange(*, method: str, path: str, query: list[list[str]], body: Any,
                          request_headers: Iterable[tuple[str, str]], status: int,
                          response_headers: Iterable[tuple[str, str]], payload: Any,
                          known_secret_values: Iterable[str] = ()) -> PrivateJsonExchange:
    """Observe one completed parse, all rows, all envelope fields, no I/O.

    The same complete JsonSchemaObserver handles request, headers and response.
    Reports contain no scalar values; known secrets in dynamic keys are masked.
    Header value retention uses a deny-by-default allowlist, preserving allowed
    duplicate occurrences. No array sampling or lifetime accumulation occurs.
    """
    raw: dict[str, Any] = {"version": EXCHANGE_OBSERVATION_VERSION,
           "secret_policy_version": EXCHANGE_SECRET_POLICY_VERSION,
           "header_policy_version": EXCHANGE_HEADER_POLICY_VERSION,
           "request": {"method": method, "path": path, "query": _query(query), "body": body,
                       "headers": _headers(request_headers)},
           "response": {"status": status, "headers": _headers(response_headers), "body": payload}}
    report = JsonSchemaObserver().observe(raw).report()
    # Header policy excludes unknown/challenge/cookie values even when their
    # names look neutral. Known aliases elsewhere must still be removed.
    secrets = _secret_literals(raw, known_secret_values)
    for direction in ("request", "response"):
        headers = raw[direction]["headers"]
        raw[direction]["headers"] = {key: values for key, values in headers.items() if key in _VALUE_HEADERS}
    # Fixed wrapper names must not disappear when a short secret coincides
    # with a word such as "body". Only source-owned keys/values are filtered.
    private = {"version": EXCHANGE_OBSERVATION_VERSION,
               "secret_policy_version": EXCHANGE_SECRET_POLICY_VERSION,
               "header_policy_version": EXCHANGE_HEADER_POLICY_VERSION,
               "request": {"method": _private_copy(method, secrets), "path": _private_copy(path, secrets),
                           "query": _private_copy(raw["request"]["query"], secrets),
                           "body": _private_copy(body, secrets),
                           "headers": _private_copy(raw["request"]["headers"], secrets)},
               "response": {"status": status, "body": _private_copy(payload, secrets),
                            "headers": _private_copy(raw["response"]["headers"], secrets)}}
    return PrivateJsonExchange(private, _redact_schema(report, secrets))
