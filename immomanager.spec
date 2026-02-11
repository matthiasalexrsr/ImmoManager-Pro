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

# Project root
ROOT = os.path.abspath('.')

# Collect bundled data files
backend_data = []

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

alembic_dir = os.path.join(ROOT, 'alembic')
if os.path.isdir(alembic_dir):
    for dirpath, dirnames, filenames in os.walk(alembic_dir):
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
    hiddenimports=[
        # --- Uvicorn internals ---
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
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
        'backend.services.portal_adapters',
        'backend.services.task_queue',
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
        # --- Third-party ---
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.postgresql',
        'aiosqlite',
        'pydantic_settings',
        'multipart',
        'jose',
        'alembic',
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
