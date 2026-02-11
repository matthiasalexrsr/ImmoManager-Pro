#!/usr/bin/env python3
"""Build ImmoManager Pro as a standalone Windows .exe using PyInstaller.

Usage:
    python scripts/build_exe.py          # Build directory bundle
    python scripts/build_exe.py --onefile # Build single .exe file

Prerequisites:
    pip install pyinstaller

Output:
    dist/ImmoManager-Pro/ImmoManager-Pro.exe  (directory mode)
    dist/ImmoManager-Pro.exe                  (one-file mode)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_pyinstaller():
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller nicht installiert. Installiere...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build_frontend():
    """Install npm deps and build the frontend."""
    frontend_dir = ROOT / "frontend"
    if not (frontend_dir / "package.json").is_file():
        print("WARNUNG: Kein frontend/package.json gefunden. Frontend wird nicht eingebunden.")
        return

    import shutil

    if shutil.which("npm") is None:
        if (frontend_dir / "dist").is_dir():
            print("Frontend dist/ bereits vorhanden (npm nicht verfügbar).")
        else:
            print("FEHLER: npm nicht gefunden und frontend/dist existiert nicht.")
            sys.exit(1)
        return

    print("Installiere Frontend-Abhängigkeiten...")
    subprocess.check_call(["npm", "install"], cwd=str(frontend_dir))
    print("Baue Frontend...")
    subprocess.check_call(["npm", "run", "build"], cwd=str(frontend_dir))


def build_exe(onefile=False):
    """Run PyInstaller with the spec file."""
    spec_file = ROOT / "immomanager.spec"

    if onefile:
        # For one-file mode, modify the spec dynamically
        print("Baue einzelne .exe-Datei...")
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--name", "ImmoManager-Pro",
            "--add-data", f"{ROOT / 'i18n'}{':' if sys.platform != 'win32' else ';'}i18n",
            "--add-data", f"{ROOT / 'frontend' / 'dist'}{':' if sys.platform != 'win32' else ';'}frontend/dist",
            "--hidden-import", "uvicorn.logging",
            "--hidden-import", "uvicorn.loops.auto",
            "--hidden-import", "uvicorn.protocols.http.auto",
            "--hidden-import", "uvicorn.protocols.websockets.auto",
            "--hidden-import", "uvicorn.lifespan.on",
            "--hidden-import", "backend.app",
            "--hidden-import", "sqlalchemy.dialects.sqlite",
            "--hidden-import", "aiosqlite",
            "--hidden-import", "pydantic_settings",
            "--hidden-import", "cffi",
            "--hidden-import", "cryptography",
            "--console",
            str(ROOT / "backend" / "__main__.py"),
        ]
        subprocess.check_call(cmd, cwd=str(ROOT))
    else:
        print("Baue .exe-Verzeichnis-Bundle...")
        subprocess.check_call(
            [sys.executable, "-m", "PyInstaller", "--clean", str(spec_file)],
            cwd=str(ROOT),
        )


def main():
    onefile = "--onefile" in sys.argv

    print("=" * 60)
    print("ImmoManager Pro – Build .exe")
    print("=" * 60)

    check_pyinstaller()
    build_frontend()
    build_exe(onefile=onefile)

    print()
    print("=" * 60)
    if onefile:
        exe_path = ROOT / "dist" / "ImmoManager-Pro.exe"
    else:
        exe_path = ROOT / "dist" / "ImmoManager-Pro" / "ImmoManager-Pro.exe"
    print(f"Build fertig: {exe_path}")
    print()
    print("Starten mit:")
    print(f"  {exe_path}")
    print(f"  {exe_path} --seed     # Mit Demo-Daten")
    print(f"  {exe_path} --port 9000")
    print("=" * 60)


if __name__ == "__main__":
    main()
