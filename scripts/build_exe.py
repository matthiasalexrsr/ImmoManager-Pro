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
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_dependencies():
    """Ensure PyInstaller and project dependencies are installed."""
    print("Installiere die festgelegten Build- und Laufzeitversionen...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / 'requirements-pip.txt')], cwd=ROOT)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / 'requirements-runtime.txt'),
                           "-r", str(ROOT / 'requirements-build.txt'), "-c", str(ROOT / 'constraints.txt')], cwd=ROOT)


def build_frontend(with_document_tools=False):
    """Install npm deps and build the frontend."""
    frontend_dir = ROOT / "frontend"
    if with_document_tools:
        os.environ['IMMO_BUILD_DOCUMENT_TOOLS'] = '1'
        from tools.build_profile import document_tools
        document_tools()
    else:
        os.environ['IMMO_BUILD_DOCUMENT_TOOLS'] = '0'
    if not (frontend_dir / "package.json").is_file():
        print("WARNUNG: Kein frontend/package.json gefunden. Frontend wird nicht eingebunden.")
        return

    import shutil

    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if npm is None:
        if (frontend_dir / "dist").is_dir():
            print("Frontend dist/ bereits vorhanden (npm nicht verfuegbar).")
        else:
            print("FEHLER: npm nicht gefunden und frontend/dist existiert nicht.")
            sys.exit(1)
        return

    print("Installiere Frontend-Abhaengigkeiten...")
    subprocess.check_call([npm, "ci"], cwd=str(frontend_dir))
    if with_document_tools:
        editor_dir = ROOT / "optional" / "document-editor"
        subprocess.check_call([npm, "ci"], cwd=str(editor_dir))
        subprocess.check_call([npm, "run", "build"], cwd=str(editor_dir))
    print("Baue Frontend...")
    subprocess.check_call([npm, "run", "build"], cwd=str(frontend_dir))


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
    # PyInstaller also copies deeply nested template and resource directories.
    # Use extended Win32 paths before any destination directory is created.
    from backend.services.filesystem_paths import filesystem_path
    cmd.extend(["--noconfirm", "--distpath", str(filesystem_path(ROOT / "dist")),
                "--workpath", str(filesystem_path(ROOT / "build"))])
    cmd.append(str(spec_file))
    subprocess.check_call(cmd, cwd=str(ROOT))


def main():
    clean = "--clean" in sys.argv

    print("=" * 60)
    print("ImmoManager Pro – Build .exe")
    print("=" * 60)

    check_dependencies()
    build_frontend(with_document_tools="--with-document-tools" in sys.argv)
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
