"""Links a person opens from the app (a provider's customer portal): web addresses only."""

import re
from urllib.parse import urlsplit

MAX_LENGTH = 500
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+-]*):")


def web_link(value: str | None) -> str | None:
    """An empty value is no link; anything else must be an http(s) address with a host.

    Other schemes (javascript:, file:, data:) would run or open something else from a click.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    scheme = _SCHEME.match(text)
    if scheme is None:
        text = "https://" + text                    # "portal.stadtwerke.de" is meant as a web address
    elif scheme.group(1).lower() not in ("http", "https"):
        raise ValueError("Bitte eine Webadresse angeben, z. B. https://kundenportal.anbieter.de")
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or any(c.isspace() for c in text):
        raise ValueError("Bitte eine Webadresse angeben, z. B. https://kundenportal.anbieter.de")
    if len(text) > MAX_LENGTH:
        raise ValueError(f"Die Webadresse ist länger als {MAX_LENGTH} Zeichen")
    return text
