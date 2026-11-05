"""The new desktop GUI must carry its exact Tcl/Tk runtime license notices."""
import json
import sys

import pytest

from tools import third_party_notices as notices


def test_exact_tcl_tk_release_terms_are_present_and_hashed():
    rows = notices.tcl_tk_license_sources({"Tcl": "8.6.15", "Tk": "8.6.15"})
    assert [row[:2] for row in rows] == [("Tcl", "8.6.15"), ("Tk", "8.6.15")]
    for name, version, expression, path, source in rows:
        text = path.read_text(encoding="utf-8")
        assert "notice is included verbatim in any distributions" in text
        assert name.lower() in source["url"] and version == source["version"]
        assert expression == "Unmodified upstream license.terms"


def test_unrecognized_runtime_version_cannot_reuse_a_different_license():
    with pytest.raises(RuntimeError, match="Missing exact"):
        notices.tcl_tk_license_sources({"Tcl": "9.0.0"})


def test_changed_license_text_is_rejected(tmp_path, monkeypatch):
    folder = tmp_path / "packaging/third-party"
    folder.mkdir(parents=True)
    entries = json.loads((notices.ROOT / "packaging/third-party/tcl-tk-licenses.json").read_text(encoding="utf-8"))
    (folder / "tcl-tk-licenses.json").write_text(json.dumps(entries), encoding="utf-8")
    (folder / entries[0]["filename"]).write_text("different text", encoding="utf-8")
    monkeypatch.setattr(notices, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        notices.tcl_tk_license_sources({"Tcl": "8.6.15"})


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows Tcl/Tk PE resources")
def test_actual_windows_runtime_has_matching_license_sources():
    pytest.importorskip("PyInstaller", reason="The notice collector requires the explicitly selected PyInstaller build runtime")
    versions = notices.windows_tcl_tk_versions()
    assert set(versions) == {"Tcl", "Tk"}
    assert len(notices.tcl_tk_license_sources(versions)) == 2
