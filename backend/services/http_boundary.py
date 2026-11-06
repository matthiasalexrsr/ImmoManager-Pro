"""Reject untrusted HTTP authorities and cross-site mutations before account work."""

import ipaddress
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def authority(value: str) -> tuple[str, int | None]:
    """A single ASCII Host authority, including bracketed IPv6; never a URL."""
    if (not value or len(value) > 260 or any(c in value for c in "/?#@\\")
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value)):
        raise ValueError("Invalid authority")
    if value.startswith("["):
        if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]{1,5})?", value):
            raise ValueError("Invalid bracketed authority")
    elif not re.fullmatch(r"[^:]+(?::[0-9]{1,5})?", value):
        raise ValueError("Invalid authority")
    parsed = urlsplit("http://" + value)
    host = parsed.hostname
    port = parsed.port
    if not host or parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid authority")
    if value.endswith(":") or port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    if ":" in host:
        host = str(ipaddress.IPv6Address(host))
        if not value.startswith("["):
            raise ValueError("IPv6 must be bracketed")
    elif not re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]{0,251}[a-z0-9])?\.?", host) or ".." in host:
        raise ValueError("Invalid host")
    return host.rstrip("."), port


def origin(value: str) -> tuple[str, str, int]:
    if any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError("Invalid origin")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Invalid origin")
    host, port = authority(parsed.netloc)
    return parsed.scheme, host, port or (443 if parsed.scheme == "https" else 80)


def configured_hosts(trusted: list[str], origins: list[str], portal_url: str, *, production: bool) -> list[str]:
    hosts = {"localhost", "127.0.0.1", "::1"}
    if not production:
        hosts.add("testserver")
    for item in trusted:
        # Configured hosts contain no port, URL or wildcard. IPv6 is bracketed.
        host, port = authority(item)
        if port is not None:
            raise ValueError("TRUSTED_HOSTS must contain hostnames without ports")
        hosts.add(host)
    for item in [*origins, portal_url]:
        if item and item != "*":
            parsed = urlsplit(item)
            # PORTAL_PUBLIC_URL may include its explicit application path.
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("Configured public URL must use HTTP or HTTPS")
            hosts.add(authority(parsed.netloc)[0])
    return sorted(hosts)


class HTTPBoundaryMiddleware:
    def __init__(self, app, *, allowed_hosts: list[str], allowed_origins: list[str]):
        self.app = app
        self.allowed_hosts = frozenset(allowed_hosts)
        self.allowed_origins = frozenset(origin(item) for item in allowed_origins if item != "*")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        try:
            hosts = [value.decode("ascii") for key, value in headers if key.lower() == b"host"]
            if len(hosts) != 1:
                raise ValueError("One Host is required")
            host, port = authority(hosts[0])
            if host not in self.allowed_hosts:
                raise ValueError("Host is not configured")
        except (ValueError, UnicodeError):
            return await JSONResponse({"detail": "Ungültiger oder nicht freigegebener Hostname."}, status_code=400)(scope, receive, send)
        if scope["method"] in _UNSAFE:
            origins = [value.decode("latin-1") for key, value in headers if key.lower() == b"origin"]
            sites = [value for key, value in headers if key.lower() == b"sec-fetch-site"]
            try:
                if len(origins) > 1:
                    raise ValueError("One Origin is required")
                if origins:
                    claimed = origin(origins[0])
                    scheme = scope.get("scheme", "http")
                    same = (scheme, host, port or (443 if scheme == "https" else 80))
                    if claimed != same and claimed not in self.allowed_origins:
                        raise ValueError("Origin is not allowed")
                elif any(site.strip().lower() == b"cross-site" for site in sites):
                    raise ValueError("Cross-site mutation without Origin")
            except ValueError:
                return await JSONResponse({"detail": "Diese Anfrage stammt nicht von einer freigegebenen Oberfläche."}, status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)
