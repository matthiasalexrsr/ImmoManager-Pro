"""Assemble this owned test package, then verify every extracted byte."""
import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
from backend.services.filesystem_paths import filesystem_path  # noqa: E402
from tools.e_invoice_notices import verify_catalog  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bundle", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--extract", type=Path, required=True)
parser.add_argument("--runtime-commit", required=True)
options = parser.parse_args()
SOURCE, OUT, EXTRACT = (path.resolve() for path in (options.bundle, options.output, options.extract))
assert all(path.is_relative_to(R / "artifacts") for path in (SOURCE, OUT, EXTRACT))
assert (SOURCE / "ImmoManager-Pro.exe").is_file()
assert len(options.runtime_commit) == 40 and all(c in "0123456789abcdef" for c in options.runtime_commit)
verify_catalog(SOURCE / "_internal/THIRD_PARTY_NOTICES")
assert not OUT.exists() and not EXTRACT.exists()
OUT.mkdir()
EXTRACT.mkdir()

def digest(path):
    with filesystem_path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

files = {}
for path in sorted(filesystem_path(SOURCE).rglob("*")):
    if path.is_file() and path.name != "immo_startup.log" and "__pycache__" not in path.parts:
        relative = "ImmoManager-Pro/" + path.relative_to(filesystem_path(SOURCE)).as_posix()
        files[relative] = {"sha256": digest(path), "bytes": path.stat().st_size, "path": path}

readme = """ImmoManager Pro – Integrationstest, 26.10.2026
=============================================

Dieses Windows-Testpaket enthält den integrierten Rechnungseingang, sichere
Zahlungsvorschläge, Arbeitsabläufe, Migration, Kundenexport, Mieter- und
Eigentümerportal, Datenschutzentscheidungen und Quellenbelege.

Lokaler Test
-----------
1. Das gesamte ZIP in einen neuen beschreibbaren Ordner entpacken.
2. Start-Test.cmd starten. Es verwendet ausschließlich den Unterordner
   Testdaten neben dieser Datei und http://127.0.0.1:18765.
3. Beim ersten Start ein eigenes Eigentümerkonto anlegen. Es gibt keine
   vorgegebenen Zugangsdaten und keine mitgelieferte Kundendatenbank.
4. Rechnungseingang: Rechnungsprüfung -> E-Rechnungseingang.
   Import/Kundenexport, Portalverwaltung und Datenschutz: Einstellungen.
5. Für einen eingeladenen Portalnutzer einen separaten Browserkontext öffnen.
   Link, Passwort und veröffentlichte Dokumente gehören zur externen Identität.
6. Zum Beenden im Programmfenster Strg+C drücken.

Start-Test.cmd aktiviert ausdrücklich den lokalen Portal-Testmodus und die
dauerhaften Hintergrundjobs. Er ist für einen Internetbetrieb ungeeignet.
Die tatsächliche Kundenhosting-Adresse benötigt HTTPS und eine eigene isolierte
Instanz einschließlich Datenbank, Schlüssel, Speicher und Backups.

Bestehende Daten aktualisieren
-----------------------------
Nicht den Testdatenordner mit einer bestehenden Installation vermischen.
Migration-und-Rueckfall.md beschreibt Upgrade, Sicherung, Rückfall und den
erforderlichen Datenschutzabgleich nach einer Wiederherstellung. Kundenexporte
ersetzen keine Betriebssicherung. Den alten Programmstand und ein geprüftes
Vollbackup vor einem Upgrade aufbewahren.

Paketnachweis und Lizenzen
------------------------
PAKET-INHALT.json enthält Dateigrößen und SHA-256. Alle Lizenztexte und
entsprechenden Quellarchive befinden sich unverändert unter
ImmoManager-Pro/_internal/THIRD_PARTY_NOTICES. Im gestarteten Programm:
http://127.0.0.1:18765/api/v1/legal
Die jeweiligen Drittanbieterbedingungen gelten auch bei kommerziellem Angebot.

Der zugehörige Ergebnisbericht nennt die tatsächlichen Prüfungen und Grenzen.
Dieses Testpaket ist unsigniert. Die im Plan gesondert genannten Nachweise für
Herausgebersignierung, Anbieterzugänge und Zielhosting bleiben separat erforderlich.
"""
launcher = r"""@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Test.ps1" %*
if errorlevel 1 pause
endlocal
"""
isolated_launcher = r'''param(
    [switch]$NoBrowser,
    [ValidateRange(1024, 65535)][int]$Port = 18765
)
$ErrorActionPreference = 'Stop'
$testRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$binary = Join-Path $testRoot 'ImmoManager-Pro\ImmoManager-Pro.exe'
$testData = Join-Path $testRoot 'Testdaten'
if (Test-Path -LiteralPath (Join-Path (Split-Path $binary) '.env')) {
    throw 'Bitte ein unveraendertes Testpaket in einem eigenen Ordner verwenden: .env neben der EXE gefunden.'
}
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $binary
$start.WorkingDirectory = $testRoot
$start.UseShellExecute = $false
$start.Arguments = '--host 127.0.0.1 --port ' + $Port + ' --data-dir "' + $testData + '"'
if ($NoBrowser) { $start.Arguments += ' --no-browser' }
$start.EnvironmentVariables.Clear()
foreach ($name in @('SystemRoot','WINDIR','PATH','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','ProgramData','ProgramFiles','ProgramFiles(x86)','COMSPEC')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($null -ne $value) { $start.EnvironmentVariables[$name] = $value }
}
$localSettings = @{
    DATA_DIR = $testData
    DATABASE_URL = 'sqlite:///' + (Join-Path $testData 'immo_manager.db').Replace('\','/')
    UPLOADS_DIR = (Join-Path $testData 'uploads')
    BACKUP_DIR = (Join-Path $testData 'backups')
    LOG_FILE = (Join-Path $testData 'logs\immomanager.log')
    INTEGRATION_STATE_FILE = (Join-Path $testData 'integrations.json')
    SECRET_KEY_FILE = (Join-Path $testData 'keyring.json')
    SQLITE_PERSISTENT_STORE = 'true'
    ALLOW_INMEMORY_FALLBACK = 'false'
    PORTAL_ENABLED = 'true'
    PORTAL_LOCAL_TEST_MODE = 'true'
    PORTAL_PUBLIC_URL = "http://127.0.0.1:$Port"
    CORS_ORIGINS = "http://127.0.0.1:$Port"
    JOB_SCHEDULER_ENABLED = 'true'
    IMMO_TESTVERSION = 'false'
}
foreach ($entry in $localSettings.GetEnumerator()) { $start.EnvironmentVariables[$entry.Key] = $entry.Value }
$process = [System.Diagnostics.Process]::Start($start)
try { $process.WaitForExit(); exit $process.ExitCode }
finally { $process.Dispose() }
'''
extras = {
    "LIES MICH.txt": readme.encode("utf-8-sig"),
    "Start-Test.cmd": launcher.replace("\n", "\r\n").encode("ascii"),
    "Start-Test.ps1": isolated_launcher.replace("\n", "\r\n").encode("ascii"),
    "Migration-und-Rueckfall.md": (R / "docs/INTEGRATION_MIGRATION.md").read_bytes(),
}
for name, value in extras.items():
    path = OUT / name
    path.write_bytes(value)
    files[name] = {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value), "path": path}
manifest = {
    "format": "immomanager-integration-test-package/1",
    "runtime_source_commit": options.runtime_commit,
    "runtime_note": "Built from this committed runtime; later documentation changes do not alter the application.",
    "signed": False,
    "files": [{"path": name, **{k: v for k, v in item.items() if k != "path"}} for name, item in files.items()],
}
manifest_raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
archive_path = OUT / "ImmoManager-Pro-Integration-Test-Windows.zip"
with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for name, item in files.items():
        archive.write(item["path"], name)
    archive.writestr("PAKET-INHALT.json", manifest_raw)
with zipfile.ZipFile(archive_path) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist()) == len(files) + 1
    for entry in archive.infolist():
        assert not entry.filename.startswith("/") and ".." not in Path(entry.filename).parts
        target = filesystem_path(EXTRACT / entry.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(entry) as reader, target.open("wb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
for name, item in files.items():
    target = EXTRACT / name
    assert digest(target) == item["sha256"]
    assert filesystem_path(target).stat().st_size == item["bytes"]
result = {"archive": str(archive_path), "sha256": digest(archive_path), "bytes": archive_path.stat().st_size,
          "verified_files": len(files), "extracted": str(EXTRACT), "all_hashes_match": True}
(OUT / "package-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
