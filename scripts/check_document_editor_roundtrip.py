"""Independent OOXML oracle for the real synthetic browser editor roundtrip."""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def check(original: bytes, edited: bytes, marker: str) -> dict:
    with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(edited)) as after:
        source = ET.fromstring(before.read("word/document.xml"))
        target = ET.fromstring(after.read("word/document.xml"))
        source_text = "".join(node.text or "" for node in source.iter(W + "t"))
        target_text = "".join(node.text or "" for node in target.iter(W + "t"))
        assert marker in target_text, "The actual browser edit is absent from the saved DOCX"
        assert target_text.replace(marker, "", 1) == source_text, "Existing document text changed or disappeared"
        for name in ("tbl", "tr", "tc", "ins", "footnoteReference", "headerReference", "footerReference"):
            assert len(list(target.iter(W + name))) == len(list(source.iter(W + name))), f"Lost or duplicated {name}"
        for part in ("word/header1.xml", "word/footer1.xml", "word/footnotes.xml", "word/comments.xml"):
            initial = ET.fromstring(before.read(part))
            result = ET.fromstring(after.read(part))
            assert "".join(node.text or "" for node in result.iter(W + "t")) == "".join(
                node.text or "" for node in initial.iter(W + "t")), f"Changed {part} text"
        media_before = {hashlib.sha256(before.read(name)).hexdigest() for name in before.namelist() if name.startswith("word/media/")}
        media_after = {hashlib.sha256(after.read(name)).hexdigest() for name in after.namelist() if name.startswith("word/media/")}
        assert media_before <= media_after, "Embedded original image bytes disappeared"
        return {"native_ooxml": True, "edit_present": True, "all_existing_text_preserved": True,
                "tables_and_revision_counts_preserved": True, "headers_footers_footnotes_comments_preserved": True,
                "image_bytes_preserved": True, "source_sha256": hashlib.sha256(original).hexdigest(),
                "edited_sha256": hashlib.sha256(edited).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("edited", type=Path)
    parser.add_argument("--marker", default="QA_BROWSER_AENDERUNG_20261016 ")
    options = parser.parse_args()
    result = check(options.original.read_bytes(), options.edited.read_bytes(), options.marker)
    output = options.edited.with_suffix(".check.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
