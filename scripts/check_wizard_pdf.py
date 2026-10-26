"""Compare both downloaded wizard PDFs with the actual visible browser preview."""
import argparse
import json
import re
from pathlib import Path

from pypdf import PdfReader


def check(folder: Path) -> list[dict]:
    preview = (folder / "preview.txt").read_text(encoding="utf-8")
    def normalize(value):
        return re.sub(r"\s+", "", value)
    results = []
    for name in ("wizard-server.pdf", "wizard-browser-fallback.pdf"):
        reader = PdfReader(folder / name)
        texts = [page.extract_text() for page in reader.pages]
        assert texts and all(text.strip() for text in texts), f"Empty PDF page: {name}"
        assert normalize(preview) == normalize("\n".join(texts)), f"PDF differs from the visible contract: {name}"
        results.append({"file": name, "pages": len(texts), "complete_preview_text_equal": True})
    (folder / "pdf-content-check.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    print(json.dumps(check(parser.parse_args().folder), indent=2))
