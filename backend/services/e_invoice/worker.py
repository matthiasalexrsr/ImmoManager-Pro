"""Bounded extraction child; has no application configuration, database or auth."""
import json
import os
import sys
from pathlib import Path

from . import parser


def main(folder_argument=None):
    folder = Path(folder_argument or sys.argv[1]).resolve(strict=True)
    owned = os.environ.get("E_INVOICE_READ_DIR")
    if not owned or folder != Path(owned).resolve(strict=True) or not folder.name.startswith("immo-e-invoice-read-"):
        raise RuntimeError("Owned invoice work directory required")
    try:
        source = folder / "source.bin"
        if source.stat().st_size > parser.MAX_FILE:
            raise parser.Unreadable("Der Originalbeleg überschreitet 25 MiB.")
        container, xml, metadata = parser.extract(source.read_bytes())
        reading = parser.read(xml, container)
        (folder / "invoice.xml").write_bytes(xml)
        result = {"container": container, "reading": {**reading, **metadata}}
    except parser.Unreadable as error:
        result = {"error": str(error)}
    raw = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(raw) > 4 * 1024 * 1024:
        raw = json.dumps({"error": "Die Lesefassung überschreitet die zulässige Größe."}).encode("utf-8")
    (folder / "result.json").write_bytes(raw)


if __name__ == "__main__":
    main()
