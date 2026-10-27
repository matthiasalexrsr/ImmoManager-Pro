"""XML from uploads, bank files and office archives, read without entities or DTD tricks (defusedxml).

A refused document raises ElementTree's own ParseError, so callers keep treating it as unreadable XML.
"""

from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring as _fromstring


def fromstring(data: str | bytes) -> Element:
    try:
        return _fromstring(data)
    except DefusedXmlException as exc:
        raise ParseError(f"Unsichere XML-Struktur abgelehnt: {type(exc).__name__}") from exc
