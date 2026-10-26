"""Keep maliciously compressed PDFs/XML outside the application process."""
import json
import sys
import tempfile
from pathlib import Path

from . import parser
from .validator import MAX_REPORT, ValidatorUnavailable, _run


def read_isolated(content: bytes) -> tuple[str, bytes, dict]:
    with tempfile.TemporaryDirectory(prefix="immo-e-invoice-read-") as directory:
        folder = Path(directory)
        (folder / "source.bin").write_bytes(content)
        argv = ([sys.executable, "e-invoice-read-worker", str(folder)] if getattr(sys, "frozen", False) else
                [sys.executable, "-m", "backend.services.e_invoice.worker", str(folder)])
        code, _stdout, _stderr = _run(argv, folder, environment={"E_INVOICE_READ_DIR": str(folder),
            "PYTHONPATH": str(Path(__file__).resolve().parents[3]), "PYTHONUTF8": "1"})
        result_path = folder / "result.json"
        if code != 0 or not result_path.is_file() or result_path.stat().st_size > MAX_REPORT:
            raise ValidatorUnavailable("Die abgeschottete Belegauswertung wurde nicht vollständig beendet.")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if "error" in result:
            raise parser.Unreadable(result["error"])
        xml_path = folder / "invoice.xml"
        if not xml_path.is_file() or xml_path.stat().st_size > parser.MAX_XML:
            raise ValidatorUnavailable("Die Rechnungs-XML konnte nicht vollständig extrahiert werden.")
        return result["container"], xml_path.read_bytes(), result["reading"]
