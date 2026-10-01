"""Generic synthetic XML only; no inferred Buhl tags, customer files or schema."""

import codecs
import hashlib

import pytest

from tools import buhl_xml_probe as probe


def entry(signature, path):
    return next(value for value in signature["entries"] if value["path"] == path)


def test_original_bytes_hash_and_ordered_repeated_sibling_attribute_paths():
    source = b'<Envelope id="fixture"><Entry key="one"><Value>12.34</Value></Entry><Note /><Entry key="two"><Value>56.78</Value></Entry></Envelope>'
    signature = probe.extract_signature(source)
    assert signature["sha256"] == hashlib.sha256(source).hexdigest()
    assert signature["root_name"] == signature["root_expanded_name"] == "Envelope"
    assert signature["root_namespace_uri"] is None
    assert signature["namespace_uris"] == []
    assert signature["declared_namespace_uris"] == []
    assert [value["path"] for value in signature["entries"]] == [
        "/Envelope[1]", "/Envelope[1]/@id", "/Envelope[1]/Entry[1]", "/Envelope[1]/Entry[1]/@key",
        "/Envelope[1]/Entry[1]/Value[1]", "/Envelope[1]/Note[1]", "/Envelope[1]/Entry[2]",
        "/Envelope[1]/Entry[2]/@key", "/Envelope[1]/Entry[2]/Value[1]",
    ]
    assert entry(signature, "/Envelope[1]/Entry[2]")["position"] == 3
    assert entry(signature, "/Envelope[1]/Entry[2]/Value[1]")["value"] == "56.78"


@pytest.mark.parametrize("before,after,path", [
    (b"<Envelope><Value>12.34</Value></Envelope>", b"<Envelope><Value>12.35</Value></Envelope>", "/Envelope[1]/Value[1]"),
    (b'<Envelope><Entry value="12.34" /></Envelope>', b'<Envelope><Entry value="12.35" /></Envelope>', "/Envelope[1]/Entry[1]/@value"),
])
def test_one_cent_change_identifies_only_actual_leaf_or_attribute(before, after, path):
    compared = probe.compare_exports(before, after)
    assert compared == probe.compare_exports(before, after)
    assert compared["semantic_equal"] is False
    assert compared["added"] == compared["removed"] == []
    assert [changed["path"] for changed in compared["changed"]] == [path]
    assert compared["changed"][0]["before"]["value"] == "12.34"
    assert compared["changed"][0]["after"]["value"] == "12.35"


def test_added_removed_and_changed_are_deterministic_and_separate():
    before = b'<Envelope><Old /><Entry key="one">old</Entry><Entry key="two">stable</Entry></Envelope>'
    after = b'<Envelope><New /><Entry key="one">new</Entry><Entry key="two">stable</Entry></Envelope>'
    compared = probe.compare_exports(before, after)
    assert [value["path"] for value in compared["removed"]] == ["/Envelope[1]/Old[1]"]
    assert [value["path"] for value in compared["added"]] == ["/Envelope[1]/New[1]"]
    assert [value["path"] for value in compared["changed"]] == ["/Envelope[1]/Entry[1]"]
    assert compared == probe.compare_exports(before, after)


def test_whitespace_only_formatting_and_attribute_order_change_only_byte_hash():
    before = b'<Envelope a="first" z="last"><Entry>12.34</Entry><Empty /></Envelope>'
    after = b'<Envelope z="last" a="first">\n  <Entry>12.34</Entry>\n  <Empty> \t\r\n</Empty>\n</Envelope>'
    compared = probe.compare_exports(before, after)
    assert compared["before_sha256"] != compared["after_sha256"]
    assert compared["semantic_equal"] is True
    assert compared["added"] == compared["removed"] == compared["changed"] == []
    assert probe.extract_signature(before)["entries"] == probe.extract_signature(after)["entries"]


def test_actual_leaf_characters_and_non_xml_whitespace_are_preserved():
    source = '<Envelope><Entry>  alpha\n beta  </Entry><Other>\u00a0</Other></Envelope>'.encode()
    signature = probe.extract_signature(source)
    assert entry(signature, "/Envelope[1]/Entry[1]")["value"] == "  alpha\n beta  "
    assert entry(signature, "/Envelope[1]/Other[1]")["value"] == "\u00a0"
    changed = probe.compare_exports(source, source.replace(b"  alpha", b"alpha"))
    assert changed["semantic_equal"] is False
    assert len(changed["changed"]) == 1


def test_namespace_prefixes_default_namespaces_and_attribute_order_are_semantic():
    before = b'<a:Envelope xmlns:a="urn:fixture:export" xmlns:q="urn:fixture:attribute" q:id="one" plain="two"><a:Entry q:key="three">text</a:Entry></a:Envelope>'
    after = b'<Envelope xmlns="urn:fixture:export" xmlns:b="urn:fixture:attribute" xmlns:unused="urn:unused" plain="two" b:id="one"><Entry b:key="three">text</Entry></Envelope>'
    signature = probe.extract_signature(before)
    assert signature["root_name"] == "Envelope"
    assert signature["root_expanded_name"] == "{urn:fixture:export}Envelope"
    assert signature["root_namespace_uri"] == "urn:fixture:export"
    assert signature["namespace_uris"] == ["urn:fixture:attribute", "urn:fixture:export"]
    assert signature["declared_namespace_uris"] == ["urn:fixture:attribute", "urn:fixture:export"]
    assert probe.extract_signature(after)["declared_namespace_uris"] == ["urn:fixture:attribute", "urn:fixture:export", "urn:unused"]
    assert probe.compare_exports(before, after)["semantic_equal"] is True
    assert probe.compare_exports(before, before.replace(b"urn:fixture:export", b"urn:fixture:other"))["semantic_equal"] is False


def test_same_local_sibling_names_in_different_namespaces_have_independent_indexes():
    source = b'<Envelope xmlns:a="urn:a" xmlns:b="urn:b"><a:Entry /><b:Entry /><a:Entry /></Envelope>'
    paths = [value["path"] for value in probe.extract_signature(source)["entries"]]
    assert paths == ["/Envelope[1]", "/Envelope[1]/{urn:a}Entry[1]", "/Envelope[1]/{urn:b}Entry[1]", "/Envelope[1]/{urn:a}Entry[2]"]


def test_uri_path_delimiters_are_escaped_without_changing_namespace_identity():
    signature = probe.extract_signature(b'<Envelope xmlns="https://example.invalid/xml~fixture"><Entry /></Envelope>')
    assert signature["root_namespace_uri"] == "https://example.invalid/xml~fixture"
    assert signature["entries"][0]["path"] == "/{https:~1~1example.invalid~1xml~0fixture}Envelope[1]"


def test_mixed_content_and_different_sibling_reordering_are_not_silently_ignored():
    before = b"<Envelope>alpha <Entry>inside</Entry> beta</Envelope>"
    signature = probe.extract_signature(before)
    assert entry(signature, "/Envelope[1]")["value"] == "alpha "
    assert entry(signature, "/Envelope[1]/Entry[1]/#tail")["value"] == " beta"
    assert probe.compare_exports(before, before.replace(b" beta", b" gamma"))["changed"][0]["path"].endswith("/#tail")
    compared = probe.compare_exports(b"<Envelope><First /><Second /></Envelope>", b"<Envelope><Second /><First /></Envelope>")
    assert compared["semantic_equal"] is False
    assert [value["path"] for value in compared["changed"]] == ["/Envelope[1]/First[1]", "/Envelope[1]/Second[1]"]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be", "iso-8859-1"])
def test_valid_declared_encodings_and_boms_keep_the_same_unicode_content(encoding):
    declared = encoding.replace("-sig", "")
    xml = f'<?xml version="1.0" encoding="{declared}"?><Envelope><Entry>\u00e4\u00df</Entry></Envelope>'
    data = xml.encode(encoding)
    if encoding in {"utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"}:
        data = {"utf-16-le": codecs.BOM_UTF16_LE, "utf-16-be": codecs.BOM_UTF16_BE,
                "utf-32-le": codecs.BOM_UTF32_LE, "utf-32-be": codecs.BOM_UTF32_BE}[encoding] + data
    signature = probe.extract_signature(data)
    assert signature["sha256"] == hashlib.sha256(data).hexdigest()
    assert entry(signature, "/Envelope[1]/Entry[1]")["value"] == "\u00e4\u00df"
    assert probe.compare_exports(data, '<Envelope><Entry>\u00e4\u00df</Entry></Envelope>'.encode())["semantic_equal"] is True


@pytest.mark.parametrize("data", [b"", b"<Envelope>", b"<Envelope></Other>", b"<Envelope>&unknown;</Envelope>"])
def test_invalid_xml_has_typed_position_without_dumping_input(data):
    with pytest.raises(probe.XMLParseError) as caught:
        probe.extract_signature(data)
    assert caught.value.code == "xml_parse_error"
    assert caught.value.line >= 1
    assert caught.value.column >= 0


@pytest.mark.parametrize("data", [b"<Envelope>\xff</Envelope>", b'<?xml version="1.0" encoding="no-such-encoding"?><Envelope />',
    codecs.BOM_UTF16_LE + "<Envelope />".encode("utf-16-le")[:-1],
    codecs.BOM_UTF8 + b'<?xml version="1.0" encoding="utf-16"?><Envelope />'])
def test_invalid_or_conflicting_encoding_has_separate_typed_error(data):
    with pytest.raises(probe.XMLEncodingError) as caught:
        probe.extract_signature(data)
    assert caught.value.code == "xml_encoding_error"


@pytest.mark.parametrize("xml", ['<!DOCTYPE Envelope SYSTEM "file:///synthetic-not-a-file"><Envelope />',
    '<!DOCTYPE Envelope [<!ENTITY sample "expanded">]><Envelope>&sample;</Envelope>',
    '<!ENTITY sample SYSTEM "https://example.invalid/synthetic"><Envelope />'])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-be", "utf-32"])
def test_declarations_are_rejected_before_parser_for_all_detected_encodings(xml, encoding, monkeypatch):
    def forbidden_parse(_text):
        pytest.fail("The parser must never see a forbidden declaration")
    monkeypatch.setattr(probe.ET, "fromstring", forbidden_parse)
    with pytest.raises(probe.XMLForbiddenDeclarationError) as caught:
        probe.extract_signature(xml.encode(encoding))
    assert caught.value.code == "xml_forbidden_declaration"


def test_declaration_like_literal_text_in_comments_cdata_and_pi_is_safe_content():
    data = b'<?fixture <!DOCTYPE ignored ?> <Envelope><!-- <!ENTITY ignored --> <Entry><![CDATA[<!ENTITY literal>]]></Entry></Envelope>'
    assert entry(probe.extract_signature(data), "/Envelope[1]/Entry[1]")["value"] == "<!ENTITY literal>"


def test_iterative_walk_handles_depth_beyond_python_recursion_limit():
    depth = 1500
    data = b"<Envelope>" + b"<Entry>" * depth + b"deep value" + b"</Entry>" * depth + b"</Envelope>"
    signature = probe.extract_signature(data)
    assert len(signature["entries"]) == depth + 1
    assert signature["entries"][-1]["value"] == "deep value"
    assert signature["entries"][-1]["path"].count("/Entry[1]") == depth


def test_repeated_collection_has_no_small_business_count_cap():
    count = 10001
    data = b"<Envelope>" + b'<Entry value="synthetic" />' * count + b"</Envelope>"
    signature = probe.extract_signature(data)
    assert len(signature["entries"]) == 1 + count * 2
    assert signature["entries"][-1]["path"] == f"/Envelope[1]/Entry[{count}]/@value"


def test_signature_requires_original_bytes_instead_of_lossy_string_coercion():
    with pytest.raises(TypeError, match="original XML bytes"):
        probe.extract_signature("<Envelope />")
