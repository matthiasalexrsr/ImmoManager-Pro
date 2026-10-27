"""Validate the container deployment boundary without reading secrets from disk."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
from collections.abc import Mapping
from urllib.parse import urlsplit


def _https_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https" and parsed.hostname and parsed.port != 0
            and parsed.username is None and parsed.password is None
            and not parsed.path and not parsed.query and not parsed.fragment
        )
    except ValueError:
        return False


def _origins(value: str) -> list[str]:
    try:
        values = json.loads(value) if value.lstrip().startswith("[") else value.split(",")
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        return []
    return [item.strip() for item in values if item.strip()]


def _trusted_proxies(value: str) -> bool:
    entries = [item.strip() for item in value.split(",")]
    if not entries or any(not item or item == "*" for item in entries):
        return False
    try:
        networks = [ipaddress.ip_network(item, strict=False) for item in entries]
        return all(network.prefixlen > 0 for network in networks)
    except ValueError:
        return False


def validate(environment: Mapping[str, str]) -> list[str]:
    """Return actionable errors containing names, never supplied setting values."""
    mode = environment.get("ENVIRONMENT", "")
    if mode not in ("production", "development"):
        return ["ENVIRONMENT must explicitly be production or development."]
    if mode == "development":
        return []
    errors = []
    if len(environment.get("JWT_SECRET_KEY", "")) < 32:
        errors.append("JWT_SECRET_KEY needs at least 32 random characters.")
    if len(environment.get("BACKUP_PASSPHRASE", "")) < 32:
        errors.append("BACKUP_PASSPHRASE needs at least 32 random characters; retain it separately for recovery.")
    origins = _origins(environment.get("CORS_ORIGINS", ""))
    if not origins or not all(_https_origin(origin) for origin in origins):
        errors.append("CORS_ORIGINS must list explicit HTTPS origins without paths or wildcards.")
    if not _trusted_proxies(environment.get("FORWARDED_ALLOW_IPS", "")):
        errors.append(
            "TRUSTED_PROXY_IPS / FORWARDED_ALLOW_IPS must name the actual proxy IPs or CIDRs; wildcard trust is forbidden."
        )
    for key in (
        "ALLOW_INMEMORY_FALLBACK", "AUTO_SEED_DEMO_DATA", "DIAGNOSTICS_ALLOW_IN_PRODUCTION",
        "UPDATE_ALLOW_IN_PRODUCTION", "IMMO_TESTVERSION", "ALLOW_SELF_REGISTRATION", "PORTAL_LOCAL_TEST_MODE",
    ):
        if environment.get(key, "false").lower() not in ("false", "0", "off", "no"):
            errors.append(f"{key} must be disabled in the hosting profile.")
    if environment.get("SECURITY_HEADERS_ENABLED", "true").lower() not in ("true", "1", "on", "yes"):
        errors.append("SECURITY_HEADERS_ENABLED must be enabled in the hosting profile.")
    if environment.get("PORTAL_ENABLED", "false").lower() in ("true", "1", "on", "yes"):
        if not _https_origin(environment.get("PORTAL_PUBLIC_URL", "")):
            errors.append("An enabled portal needs PORTAL_PUBLIC_URL as an explicit HTTPS origin.")
    try:
        database = urlsplit(environment.get("DATABASE_URL", ""))
        database_valid = database.scheme in ("postgresql", "postgresql+psycopg2") and bool(
            database.hostname and database.username and database.password and database.path.strip("/")
        )
    except ValueError:
        database_valid = False
    if not database_valid:
        errors.append("DATABASE_URL must address the isolated PostgreSQL database with its own credentials.")
    return errors


def main(environment: Mapping[str, str] = os.environ) -> int:
    errors = validate(environment)
    for error in errors:
        print("Deployment configuration: " + error, file=sys.stderr)
    if not errors:
        print("Deployment configuration checked (" + environment["ENVIRONMENT"] + ").", flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
