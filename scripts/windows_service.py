"""Windows Service installer for ImmoManager Pro using NSSM.

NSSM (Non-Sucking Service Manager) wraps the application as a Windows service.
Download NSSM from: https://nssm.cc/download

Usage:
    python scripts/windows_service.py install   # Install as Windows service
    python scripts/windows_service.py remove     # Remove the service
    python scripts/windows_service.py start      # Start the service
    python scripts/windows_service.py stop       # Stop the service
    python scripts/windows_service.py status     # Check service status
"""

import os
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "ImmoManagerPro"
DISPLAY_NAME = "ImmoManager Pro"
DESCRIPTION = "Immobilienverwaltung für private Vermieter"
ROOT = Path(__file__).resolve().parent.parent


def find_nssm() -> str:
    """Find NSSM executable."""
    # Check PATH
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        nssm = Path(path_dir) / "nssm.exe"
        if nssm.exists():
            return str(nssm)
    # Check common locations
    for loc in [
        Path("C:/nssm/nssm.exe"),
        Path("C:/tools/nssm/nssm.exe"),
        ROOT / "tools" / "nssm.exe",
    ]:
        if loc.exists():
            return str(loc)
    print("FEHLER: nssm.exe nicht gefunden.")
    print("Laden Sie NSSM herunter von: https://nssm.cc/download")
    print("und fügen Sie es dem PATH hinzu.")
    sys.exit(1)


def install():
    nssm = find_nssm()
    python = sys.executable
    script = str(ROOT / "backend" / "__main__.py")

    print(f"Installiere Dienst '{SERVICE_NAME}'...")
    subprocess.run([nssm, "install", SERVICE_NAME, python, script, "--no-browser"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "DisplayName", DISPLAY_NAME], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "Description", DESCRIPTION], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppDirectory", str(ROOT)], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStdout", str(ROOT / "logs" / "service.log")], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStderr", str(ROOT / "logs" / "service-error.log")], check=True)

    (ROOT / "logs").mkdir(exist_ok=True)
    print(f"Dienst '{SERVICE_NAME}' erfolgreich installiert.")
    print(f"Starten mit: python scripts/windows_service.py start")


def remove():
    nssm = find_nssm()
    print(f"Entferne Dienst '{SERVICE_NAME}'...")
    subprocess.run([nssm, "remove", SERVICE_NAME, "confirm"], check=True)
    print("Dienst entfernt.")


def start():
    nssm = find_nssm()
    subprocess.run([nssm, "start", SERVICE_NAME], check=True)
    print(f"Dienst '{SERVICE_NAME}' gestartet.")


def stop():
    nssm = find_nssm()
    subprocess.run([nssm, "stop", SERVICE_NAME], check=True)
    print(f"Dienst '{SERVICE_NAME}' gestoppt.")


def status():
    nssm = find_nssm()
    result = subprocess.run([nssm, "status", SERVICE_NAME], capture_output=True, text=True)
    print(result.stdout.strip() or result.stderr.strip())


def main():
    if len(sys.argv) < 2:
        print("Verwendung: python scripts/windows_service.py [install|remove|start|stop|status]")
        sys.exit(1)

    commands = {"install": install, "remove": remove, "start": start, "stop": stop, "status": status}
    cmd = sys.argv[1].lower()
    if cmd not in commands:
        print(f"Unbekannter Befehl: {cmd}")
        print(f"Erlaubt: {', '.join(commands)}")
        sys.exit(1)

    commands[cmd]()


if __name__ == "__main__":
    main()
