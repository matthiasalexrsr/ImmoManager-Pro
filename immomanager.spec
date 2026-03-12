# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for ImmoManager Pro.

Build with:
    pip install pyinstaller
    pyinstaller immomanager.spec

Or use the build script:
    Windows: build.bat
    Linux:   ./build.sh

Result: dist/ImmoManager-Pro/ directory containing the executable and all dependencies.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Project root
ROOT = os.path.abspath('.')

# ---------------------------------------------------------------------------
# Verify critical dependencies are installed BEFORE building
# ---------------------------------------------------------------------------
_REQUIRED_PACKAGES = {
    'fastapi': 'fastapi',
    'starlette': 'starlette',
    'pydantic': 'pydantic',
    'uvicorn': 'uvicorn',
    'sqlalchemy': 'sqlalchemy',
    'jinja2': 'jinja2',
    'reportlab': 'reportlab',
}
_missing = []
for import_name, pip_name in _REQUIRED_PACKAGES.items():
    try:
        __import__(import_name)
    except ImportError:
        _missing.append(pip_name)
if _missing:
    print("=" * 70)
    print("FEHLER: Folgende Pakete fehlen:")
    for m in _missing:
        print(f"  - {m}")
    print()
    print("Bitte zuerst installieren:")
    print(f"  pip install {' '.join(_missing)}")
    print("Oder:  pip install -e \".[build]\"")
    print("Oder:  install.bat  /  ./install.sh")
    print("=" * 70)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Collect ALL submodules of third-party packages automatically.
# This ensures every sub-module is included even when PyInstaller's
# import analysis misses some (common on Python 3.13+).
# ---------------------------------------------------------------------------
_THIRD_PARTY_PACKAGES = [
    'fastapi',
    'starlette',
    'pydantic',
    'pydantic_core',
    'pydantic_settings',
    'uvicorn',
    'sqlalchemy',
    'alembic',
    'aiosqlite',
    'anyio',
    'sniffio',
    'h11',
    'jose',
    'cffi',
    'cryptography',
    'multipart',
    'python_multipart',
    'annotated_types',
    'typing_extensions',
    'dotenv',
    'jinja2',
    'reportlab',
]

collected_hiddenimports = []
for pkg in _THIRD_PARTY_PACKAGES:
    try:
        mods = collect_submodules(pkg)
        collected_hiddenimports += mods
        print(f"  collect_submodules('{pkg}'): {len(mods)} modules")
    except Exception as exc:
        print(f"  WARNUNG: collect_submodules('{pkg}') fehlgeschlagen: {exc}")

# Also collect data files that some packages need at runtime
collected_datas = []
for pkg in ['pydantic', 'pydantic_core', 'alembic']:
    try:
        files = collect_data_files(pkg)
        collected_datas += files
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Explicit hidden imports — these are ALWAYS included regardless of whether
# collect_submodules worked.  This is the critical safety net.
# ---------------------------------------------------------------------------
_EXPLICIT_THIRD_PARTY = [
    # FastAPI + Starlette
    'fastapi',
    'fastapi.applications',
    'fastapi.routing',
    'fastapi.params',
    'fastapi.datastructures',
    'fastapi.exceptions',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'fastapi.responses',
    'fastapi.staticfiles',
    'fastapi.templating',
    'fastapi.security',
    'fastapi.encoders',
    'fastapi.dependencies',
    'starlette',
    'starlette.applications',
    'starlette.middleware',
    'starlette.middleware.base',
    'starlette.middleware.cors',
    'starlette.routing',
    'starlette.requests',
    'starlette.responses',
    'starlette.staticfiles',
    'starlette.exceptions',
    'starlette.status',
    'starlette.types',
    'starlette.concurrency',
    'starlette.formparsers',
    'starlette.datastructures',
    'starlette.websockets',
    # Pydantic
    'pydantic',
    'pydantic.fields',
    'pydantic.main',
    'pydantic.types',
    'pydantic.errors',
    'pydantic.validators',
    'pydantic_core',
    'pydantic_settings',
    'annotated_types',
    # Uvicorn
    'uvicorn',
    'uvicorn.main',
    'uvicorn.config',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.server',
    # SQLAlchemy
    'sqlalchemy',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.dialects.postgresql',
    'sqlalchemy.orm',
    'sqlalchemy.ext.asyncio',
    'sqlalchemy.pool',
    'sqlalchemy.engine',
    'sqlalchemy.event',
    'sqlalchemy.sql',
    # Other
    'alembic',
    'aiosqlite',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    'sniffio',
    'h11',
    'jose',
    'jose.jwt',
    'jose.jws',
    'jose.backends',
    'cffi',
    'cryptography',
    'cryptography.fernet',
    'cryptography.hazmat',
    'cryptography.hazmat.primitives',
    'multipart',
    'multipart.multipart',
    'python_multipart',
    'python_multipart.multipart',
    'typing_extensions',
    'dotenv',
    'jinja2',
    'reportlab',
]

# ---------------------------------------------------------------------------
# Collect bundled data files from project
# ---------------------------------------------------------------------------
backend_data = list(collected_datas)

# Include i18n locale files
i18n_dir = os.path.join(ROOT, 'i18n')
if os.path.isdir(i18n_dir):
    for f in os.listdir(i18n_dir):
        src = os.path.join(i18n_dir, f)
        if os.path.isfile(src):
            backend_data.append((src, 'i18n'))

# Include alembic config and migrations
alembic_ini = os.path.join(ROOT, 'alembic.ini')
if os.path.isfile(alembic_ini):
    backend_data.append((alembic_ini, '.'))

# Migrations live under backend/db/migrations/ (not a top-level alembic/ dir)
migrations_dir = os.path.join(ROOT, 'backend', 'db', 'migrations')
if os.path.isdir(migrations_dir):
    for dirpath, dirnames, filenames in os.walk(migrations_dir):
        for f in filenames:
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(dirpath, ROOT)
            backend_data.append((src, rel))

# Include Mietvertrag wizard package assets/templates/static
wizard_root = os.path.join(ROOT, 'mietvertrag_wizard_fastapi_reportlab_pro')
if os.path.isdir(wizard_root):
    for dirpath, dirnames, filenames in os.walk(wizard_root):
        for f in filenames:
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(dirpath, ROOT)
            backend_data.append((src, rel))

# Include frontend dist
frontend_dist = os.path.join(ROOT, 'frontend', 'dist')
if os.path.isdir(frontend_dist):
    for dirpath, dirnames, filenames in os.walk(frontend_dist):
        for f in filenames:
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(dirpath, ROOT)
            backend_data.append((src, rel))

# Include seed_data if present
seed_file = os.path.join(ROOT, 'seed_data.py')
if os.path.isfile(seed_file):
    backend_data.append((seed_file, '.'))

# Include db/schema.sql
db_schema = os.path.join(ROOT, 'db', 'schema.sql')
if os.path.isfile(db_schema):
    backend_data.append((db_schema, 'db'))

a = Analysis(
    ['backend/__main__.py'],
    pathex=[ROOT],
    binaries=[],
    datas=backend_data,
    hiddenimports=collected_hiddenimports + _EXPLICIT_THIRD_PARTY + [
        # --- Backend core ---
        'backend.app',
        'backend.config',
        'backend.dependencies',
        'backend.models',
        'backend.storage',
        'backend.auth',
        'backend.audit',
        'backend.exceptions',
        'backend.events',
        'backend.logging_config',
        'backend.plugins',
        'backend.plugins.base',
        # --- Database ---
        'backend.db',
        'backend.db.session',
        'backend.db.orm_models',
        'backend.repositories',
        'backend.repositories.base',
        'backend.repositories.sql_store',
        # --- Domain engines ---
        'backend.domain',
        'backend.domain.lease_engine',
        'backend.domain.dunning_engine',
        'backend.domain.invoice_matching',
        'backend.domain.billing_engine',
        # --- Services ---
        'backend.services',
        'backend.services.email_service',
        'backend.services.file_storage',
        'backend.services.iban_encryption',
        'backend.services.portal_adapter',
        'backend.services.ocr_service',
        'backend.services.task_queue',
        # --- Mietvertrag wizard ---
        'mietvertrag_wizard',
        'mietvertrag_wizard.pdf_reportlab',
        # --- All routers ---
        'backend.routers',
        'backend.routers.accounts',
        'backend.routers.admin',
        'backend.routers.audit',
        'backend.routers.auth',
        'backend.routers.billing',
        'backend.routers.bookings',
        'backend.routers.budgets',
        'backend.routers.calendar',
        'backend.routers.categories',
        'backend.routers.contracts',
        'backend.routers.deposits',
        'backend.routers.documents',
        'backend.routers.escalation',
        'backend.routers.handover_protocols',
        'backend.routers.history',
        'backend.routers.i18n',
        'backend.routers.invoices',
        'backend.routers.leads',
        'backend.routers.listings',
        'backend.routers.maintenance',
        'backend.routers.notifications',
        'backend.routers.portfolios',
        'backend.routers.properties',
        'backend.routers.receivables',
        'backend.routers.rent_adjustments',
        'backend.routers.reports',
        'backend.routers.search',
        'backend.routers.tasks',
        'backend.routers.tax_rates',
        'backend.routers.tenants',
        'backend.routers.units',
        'backend.routers.viewings',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ImmoManager-Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,  # Add icon path here: 'assets/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ImmoManager-Pro',
)
