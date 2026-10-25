"""XML from uploads is read without entities: a bomb or an external reference is unreadable XML, not a hang."""

from xml.etree.ElementTree import ParseError

import pytest

from backend.services import safe_xml

BOMB = b"""<?xml version="1.0"?><!DOCTYPE b [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><r>&b;</r>"""
EXTERNAL = b"""<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>"""


@pytest.mark.parametrize("document", [BOMB, EXTERNAL])
def test_entities_are_refused_as_unreadable_xml(document):
    with pytest.raises(ParseError, match="Unsichere XML-Struktur"):
        safe_xml.fromstring(document)


def test_ordinary_office_and_bank_xml_is_read():
    root = safe_xml.fromstring(b'<w:document xmlns:w="urn:w"><w:p><w:t>Miete</w:t></w:p></w:document>')
    assert root.find(".//{urn:w}t").text == "Miete"
