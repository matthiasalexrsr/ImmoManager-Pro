"""Optional, offline LibreOffice conversion in a disposable process/profile.

No executable discovery, download, user profile or existing office process is used.
The operator supplies an absolute path to their installed local LibreOffice.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import HTTPException

from ..config import settings
from .document_formats import validate_docx


def docx_pdf(content):
    validate_docx(content)
    configured = os.environ.get("DOCUMENT_LIBREOFFICE_EXECUTABLE", "")
    executable = Path(configured)
    if not configured or not executable.is_absolute() or not executable.is_file() or executable.name.lower() not in {
            "soffice", "soffice.exe", "libreoffice"}:
        raise HTTPException(503, "Für PDF-Ausgaben aus DOCX ist noch kein lokales LibreOffice eingerichtet.")
    from ..paths import get_data_dir
    root = Path(get_data_dir()) / "document-conversion"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="export-", dir=root) as temporary:
        folder = Path(temporary)
        source = folder / "Quelle.docx"
        source.write_bytes(content)
        command = [str(executable), "-env:UserInstallation=" + (folder / "profile").as_uri(),
            "--headless", "--norestore", "--nodefault", "--nofirststartwizard", "--convert-to", "pdf:writer_pdf_Export",
            "--outdir", str(folder), str(source)]
        try:
            result = subprocess.run(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=120, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise HTTPException(503, "Die lokale PDF-Konvertierung hat das Zeitlimit erreicht. Der Auftrag bleibt wiederholbar.") from None
        except OSError:
            raise HTTPException(503, "Die lokale PDF-Konvertierung konnte nicht gestartet werden.") from None
        output = folder / "Quelle.pdf"
        if result.returncode or not output.is_file() or output.stat().st_size > settings.max_upload_size_bytes:
            raise HTTPException(422, "Die lokale Konvertierung hat keine gültige PDF-Ausgabe erzeugt.")
        value = output.read_bytes()
        if not value.startswith(b"%PDF-") or b"%%EOF" not in value[-4096:]:
            raise HTTPException(422, "Die PDF-Ausgabe ist unvollständig.")
        return value
