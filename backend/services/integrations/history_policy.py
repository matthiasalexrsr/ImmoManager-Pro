"""Explicit complete semantic JSON observation after conservative redaction."""

from ..providers.exchange_observation import (
    EXCHANGE_SECRET_POLICY_VERSION,
    _secret_key,
    _secret_literals,
    private_json_values,
)
from ..providers.schema_observation import JsonSchemaObserver, SchemaObservationError
from .history_crypto import canonical
from .history_types import HistoryError


def secret_values(config, manifest):
    known = [config.get(key) for key in manifest.secret_config_keys if isinstance(config.get(key), str)]
    return tuple(_secret_literals(config, known))


def observe(value, known):
    try:
        canonical(value)
        safe = private_json_values(value, known_secret_values=known)
        return safe, JsonSchemaObserver().observe(safe).report()
    except (HistoryError, SchemaObservationError, TypeError, ValueError, RecursionError):
        raise HistoryError("HISTORY_INPUT_INVALID", 422) from None


COMMUNICATION_IDS = {"email", "whatsapp", "deutsche-post"}
COMMUNICATION_RESULT_FIELDS = {
    "status", "code", "status_code", "external_reference", "accepted",
    "delivery_confirmed", "test_mode", "retry_automatically", "type",
}


def request_observation(integration_id, payload, config, manifest):
    known = secret_values(config, manifest)
    observed_payload = payload
    if integration_id in COMMUNICATION_IDS:
        observed_payload = {"action": payload.get("action")}
        if "test_mode" in payload:
            observed_payload["test_mode"] = bool(payload.get("test_mode"))
    safe_payload, _ = observe(observed_payload, known)
    safe_config, _ = observe(config, known)
    safe = {"payload": safe_payload if isinstance(safe_payload, dict) else {}, "config": safe_config,
        "privacy_policy": {"version": EXCHANGE_SECRET_POLICY_VERSION,
            "mail_payload_omitted": integration_id == "email",
            "communication_payload_reduced": integration_id in COMMUNICATION_IDS,
            "source": "manager_semantic_json", "unknown_secrets_without_names_or_known_literals_detectable": False}}
    schema = JsonSchemaObserver().observe(safe).report()
    return safe, schema, known


def response_observation(result, known, *, integration_id=None):
    if not isinstance(result, dict) or type(result.get("success")) is not bool:
        raise HistoryError("HISTORY_INPUT_INVALID", 422)
    message, _ = observe(result.get("message", ""), known)
    raw_details = result.get("details")
    if integration_id in COMMUNICATION_IDS and isinstance(raw_details, dict):
        raw_details = {key: value for key, value in raw_details.items() if key in COMMUNICATION_RESULT_FIELDS}
    details, _ = observe(raw_details, known)
    safe = {"success": result["success"], "message": message if isinstance(message, str) else "[redacted]"}
    if "details" in result:
        safe["details"] = details
    schema = JsonSchemaObserver().observe(safe).report()
    return safe, schema


def public_config(config, manifest):
    """Recursive secret removal, compatible top-level masked credential fields."""
    known = secret_values(config, manifest)
    safe, _ = observe(config, known)
    if not isinstance(safe, dict):
        raise HistoryError("HISTORY_INPUT_INVALID", 422)
    for key, value in config.items():
        if (key in manifest.secret_config_keys or _secret_key(key)) and value:
            safe[key] = "***"
    return safe


def preserve_config_masks(updates, current, manifest):
    """Retain explicit *** credential markers without silently changing keys."""
    def walk(value, previous, secret=False):
        if secret and value == "***":
            return previous
        if isinstance(value, dict):
            previous = previous if isinstance(previous, dict) else {}
            return {key: walk(child, previous.get(key), secret or _secret_key(key)) for key, child in value.items()}
        if isinstance(value, list):
            previous = previous if isinstance(previous, list) else []
            return [walk(child, previous[index] if index < len(previous) else None, secret) for index, child in enumerate(value)]
        return value
    return {key: walk(value, current.get(key), key in manifest.secret_config_keys or _secret_key(key)) for key, value in updates.items()}
