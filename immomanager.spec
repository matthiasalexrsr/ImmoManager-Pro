# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for ImmoManager Pro.

Build with:
    pip install pyinstaller
    pyinstaller immomanager.spec

Result: dist/ImmoManager-Pro/ (directory) or dist/ImmoManager-Pro.exe (one-file)
"""
import os
from pathlib import Path

block_cipher = None

# Project root
ROOT = os.path.abspath('.')

# Collect all backend Python files
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
        'backend.db',
        'backend.db.session',
        'backend.db.orm_models',
        'backend.domain',
        'backend.domain.lease_engine',
        'backend.domain.dunning_engine',
        'backend.domain.invoice_matching',
        'backend.domain.billing_engine',
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
