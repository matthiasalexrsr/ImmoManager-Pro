#!/usr/bin/env python3
"""Build ImmoManager Pro as a standalone executable using PyInstaller.

Usage:
    python scripts/build_exe.py          # Build directory bundle (recommended)
    python scripts/build_exe.py --clean  # Clean build artifacts first

Prerequisites:
    pip install -e ".[build]"

Output:
    dist/ImmoManager-Pro/ImmoManager-Pro.exe  (Windows)
    dist/ImmoManager-Pro/ImmoManager-Pro      (Linux/macOS)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_dependencies():
    """Ensure PyInstaller and project dependencies are installed."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller nicht installiert. Installiere Projekt mit Build-Deps...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", ".[build]"])


def build_frontend():
    """Install npm deps and build the frontend."""
    frontend_dir = ROOT / "frontend"
    if not (frontend_dir / "package.json").is_file():
        print("WARNUNG: Kein frontend/package.json gefunden. Frontend wird nicht eingebunden.")
        return

    import shutil

    if shutil.which("npm") is None:
        if (frontend_dir / "dist").is_dir():
            print("Frontend dist/ bereits vorhanden (npm nicht verfuegbar).")
        else:
            print("FEHLER: npm nicht gefunden und frontend/dist existiert nicht.")
            sys.exit(1)
        return

    print("Installiere Frontend-Abhaengigkeiten...")
    subprocess.check_call(["npm", "install"], cwd=str(frontend_dir))
    print("Baue Frontend...")
    subprocess.check_call(["npm", "run", "build"], cwd=str(frontend_dir))


def build_exe(clean=False):
    """Run PyInstaller with the spec file.

    Always uses immomanager.spec which contains the complete configuration
    including all hidden imports and data files.
    """
    spec_file = ROOT / "immomanager.spec"

    if not spec_file.is_file():
        print(f"FEHLER: Spec-Datei nicht gefunden: {spec_file}")
        sys.exit(1)

    print("Baue .exe-Verzeichnis-Bundle...")
    cmd = [sys.executable, "-m", "PyInstaller"]
    if clean:
        cmd.append("--clean")
    cmd.append(str(spec_file))
    subprocess.check_call(cmd, cwd=str(ROOT))


def main():
    clean = "--clean" in sys.argv

    print("=" * 60)
    print("ImmoManager Pro – Build .exe")
    print("=" * 60)

    check_dependencies()
    build_frontend()
    build_exe(clean=clean)

    print()
    print("=" * 60)
    if sys.platform == "win32":
        exe_path = ROOT / "dist" / "ImmoManager-Pro" / "ImmoManager-Pro.exe"
    else:
        exe_path = ROOT / "dist" / "ImmoManager-Pro" / "ImmoManager-Pro"
    print(f"Build fertig: {exe_path}")
    print()
    print("Starten mit:")
    print(f"  {exe_path}")
    print(f"  {exe_path} --seed     # Mit Demo-Daten")
    print(f"  {exe_path} --port 9000")
    print("=" * 60)


if __name__ == "__main__":
    main()
