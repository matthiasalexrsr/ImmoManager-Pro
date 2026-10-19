"""Public errors and boundaries shared by account-backed assistant transports."""

import re
from urllib.parse import urlsplit

APPLICATION_TOOLS = frozenset({"immo_search", "immo_read", "immo_related", "immo_timeline", "immo_report", "immo_document", "immo_investigate"})


def application_mcp(request: dict) -> dict | None:
    """Only a host-created loopback broker may enter a private CLI profile."""
    value = request.get("_application_mcp")
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or set(value) != {"url", "headers", "server_name", "tools"}:
            raise ValueError
        url = urlsplit(value["url"])
        if (value["server_name"] != "immomanager" or url.scheme != "http" or url.hostname != "127.0.0.1"
                or not url.port or url.username is not None or url.password is not None or url.query or url.fragment
                or url.path != '/mcp' or any(c.isspace() for c in value["url"])):
            raise ValueError
        headers = value["headers"]
        if (not isinstance(headers, dict) or set(headers) != {"Authorization"}
                or not isinstance(headers["Authorization"], str)
                or re.fullmatch(r"Bearer [A-Za-z0-9._~-]{16,2048}", headers["Authorization"]) is None):
            raise ValueError
        tools = value["tools"]
        if (not isinstance(tools, list) or not tools or any(not isinstance(tool, str) or tool not in APPLICATION_TOOLS for tool in tools)
                or len(set(tools)) != len(tools)):
            raise ValueError
        return {"url": value["url"], "headers": dict(headers), "server_name": "immomanager", "tools": list(tools)}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ProviderError("Die geschützte Verbindung zur Anwendung ist ungültig. Bitte den Auftrag neu starten.", "provider_isolation_failed") from None


class ProviderError(RuntimeError):
    def __init__(self, message: str, code: str = "provider_error", *, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain
