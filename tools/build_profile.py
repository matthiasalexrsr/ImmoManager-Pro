"""Explicit optional components for distributable builds, independent of ambient installs."""

import hashlib
import json
import os
from importlib.util import find_spec
from pathlib import Path

DOCUMENT = ["pymupdf", "fitz"]
BANK = ["fints", "mt940", "sepaxml", "xmlschema", "bleach"]
AI = ["torch", "transformers", "sentence_transformers", "huggingface_hub", "faiss"]


def document_tools():
    enabled = os.environ.get("IMMO_BUILD_DOCUMENT_TOOLS") == "1"
    if enabled:
        purpose = os.environ.get("IMMO_BUILD_PURPOSE")
        if purpose not in ("licensed", "validation"):
            raise RuntimeError(
                "Document tools require explicit licensed/validation purpose; see docs/COMMERCIAL_RELEASE.md"
            )
        if purpose == "licensed":
            data = json.loads(Path(os.environ["IMMO_LICENSE_APPROVAL_FILE"]).read_text(encoding="utf-8"))
            for name in ("PyMuPDF", "superdoc", "@superdoc/docx-engine"):
                entry = data.get("components", {}).get(name, {})
                if not entry.get("reference") or entry.get("distribution") is not True:
                    raise RuntimeError(f"Missing distribution rights record for {name}")
    return enabled


def selected_optional_packages():
    selected = (DOCUMENT if document_tools() else []) + (BANK if os.environ.get("IMMO_BUILD_BANK") == "1" else [])
    missing = [name for name in selected if find_spec(name) is None]
    if missing:
        raise RuntimeError(f"Explicitly selected components are missing: {missing}")
    return selected


def excluded_optional_packages():
    return (DOCUMENT if not document_tools() else []) + (BANK if os.environ.get("IMMO_BUILD_BANK") != "1" else []) + AI


def verify_frontend_profile(root):
    root = Path(root)
    profile = json.loads((root / "frontend/dist/product-profile.json").read_text(encoding="utf-8"))
    expected = document_tools()
    if profile.get("document_tools") is not expected or (root / "frontend/dist/document-editor").exists() != expected:
        raise RuntimeError("Frontend assets do not match the explicit product profile; rebuild the frontend")
    if profile.get("purpose") == "validation" and os.environ.get("IMMO_BUILD_PURPOSE") != "validation":
        raise RuntimeError("A validation build cannot become a customer release")


def verify_wizard_assets(root):
    """The independent wizard bundle must match its reviewed source and npm lock."""
    root = Path(root)
    vendor = root / "mietvertrag_wizard_fastapi_reportlab_pro/mietvertrag_wizard/static/mietvertrag_wizard/vendor"
    source = json.loads((vendor / "SOURCES.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    if source["version"] != lock["packages"]["node_modules/pdfmake"]["version"]:
        raise RuntimeError("Wizard PDF library differs from the audited npm lock")
    for entry in source["files"]:
        name = entry["file"]
        if Path(name).name != name:
            raise RuntimeError("Wizard asset must be a plain filename")
        payload = (vendor / name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Wizard asset checksum mismatch: {name}")
        installed = root / "frontend/node_modules/pdfmake/build" / name
        if name.endswith(".js") and installed.is_file() and payload != installed.read_bytes():
            raise RuntimeError(f"Wizard asset differs from installed npm distribution: {name}")
    return vendor, source
