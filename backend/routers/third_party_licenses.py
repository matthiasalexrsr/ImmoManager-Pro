"""Public, package-only notices and corresponding sources, also for hosted use.

No customer storage, authentication tokens or uploaded files are consulted.
Downloads use catalog IDs, never a caller-supplied filesystem path.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from ..services.e_invoice.asset_bundle import file_sha, safe_name
from ..services.filesystem_paths import filesystem_path

router = APIRouter(prefix='/legal', tags=['Lizenzhinweise'])


def notice_root() -> Path:
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    configured = os.environ.get('THIRD_PARTY_NOTICES_DIR')
    if configured:
        return Path(configured).resolve()
    if getattr(sys, 'frozen', False):
        return root / 'THIRD_PARTY_NOTICES'
    manifest = root / 'packaging/e-invoice-notices/manifest.json'
    if not manifest.is_file():
        raise HTTPException(503, 'Der Lizenzbestand wurde für diesen Quellstand noch nicht erstellt.')
    revision = hashlib.sha256(manifest.read_bytes()).hexdigest()[:12]
    return root / ('artifacts/notices-' + revision)


def catalog() -> tuple[Path, dict]:
    root = filesystem_path(notice_root())
    try:
        path = root / 'catalog.json'
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('catalog budget')
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['format'] != 'immomanager-public-notices/1':
            raise ValueError('catalog format')
        if not isinstance(data['components'], list) or not isinstance(data['files'], list):
            raise ValueError('catalog shape')
        if len(data['components']) > 5000 or len(data['files']) > 20000:
            raise ValueError('catalog entries budget')
        for row in data['components']:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in ('name', 'version', 'license')):
                raise ValueError('component shape')
        for row in data['files']:
            if (not isinstance(row, dict) or not isinstance(row.get('path'), str)
                    or type(row.get('bytes')) is not int or row['bytes'] < 0
                    or any(not re.fullmatch(r'[0-9a-f]{64}', str(row.get(key, ''))) for key in ('id', 'sha256'))):
                raise ValueError('file shape')
            safe_name(row['path'])
        return root, data
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, 'Der veröffentlichte Lizenzbestand ist unvollständig. Bitte die Paketbereitstellung prüfen.') from None


@router.get('', response_class=HTMLResponse)
def index():
    _root, data = catalog()
    def esc(value):
        return html.escape(str(value or ''), quote=True)
    components = ''.join('<tr>' + ''.join('<td>' + esc(row.get(key)) + '</td>' for key in ('name', 'version', 'license')) + '</tr>'
                         for row in data['components'])
    files = ''.join('<li><a href="/api/v1/legal/files/' + esc(row['id']) + '">' + esc(row['path']) + '</a> ('
                    + str(row['bytes']) + ' Bytes)<br><small>SHA-256: ' + esc(row['sha256']) + '</small></li>' for row in data['files'])
    return HTMLResponse('<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Lizenzen und Quellen · ImmoManager</title></head><body><main><h1>Lizenzen und Quellen</h1>'
        '<p>Diese Bestandteile behalten ihre jeweiligen Lizenzen. Die mitgelieferten Quellen dürfen gemäß diesen Bedingungen eingesehen, geändert und weitergegeben werden. '
        'Die vollständigen Texte und Copyrightvermerke stehen unten zum Download bereit, auch für Nutzer einer gehosteten Instanz.</p>'
        '<p>Die E-Rechnungsverarbeitung wendet die Veröffentlichungen EN 16931-1 und CEN/TS 16931-2 an. Die Wiedergabe erfolgt mit Erlaubnis von CEN und DIN als Copyrightinhabern. '
        'CEN und DIN gewährleisten diese Umsetzung nicht; maßgeblich bleiben ihre offiziellen Veröffentlichungen.</p>'
        '<p>GNU FreeFont ist ein getrenntes, kostenlos verfügbares Produkt. Seine unveränderte Distribution, Lizenz und entsprechenden SFD-Quellen stehen ebenfalls unten bereit.</p>'
        '<nav aria-label="Zur Anwendung"><a href="/">Verwaltung</a> · <a href="/portal">Mieter- und Eigentümerportal</a> · <a href="#downloads">Zu den Downloads</a></nav>'
        '<h2>Bestandteile</h2><table><caption>Der tatsächlich paketierte Lizenzbestand</caption><thead><tr><th scope="col">Name</th><th scope="col">Version</th><th scope="col">Lizenz</th></tr></thead><tbody>'
        + components + '</tbody></table><h2 id="downloads">Lizenztexte und Quellarchive</h2><ul>' + files + '</ul></main></body></html>',
        headers={'Cache-Control': 'public, max-age=300', 'X-Content-Type-Options': 'nosniff',
                 'Content-Security-Policy': "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"})


@router.get('/files/{identifier}')
def download(identifier: str):
    if not re.fullmatch(r'[0-9a-f]{64}', identifier):
        raise HTTPException(404, 'Lizenzdatei nicht gefunden.')
    root, data = catalog()
    matches = [entry for entry in data['files'] if entry.get('id') == identifier]
    if len(matches) != 1:
        raise HTTPException(404, 'Lizenzdatei nicht gefunden.')
    entry = matches[0]
    try:
        name = safe_name(entry['path'])
        path = root / name
        if hashlib.sha256(name.encode()).hexdigest() != identifier or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('catalog path')
        for part in [path, *path.parents]:
            if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
                raise ValueError('catalog link')
            if part == root:
                break
        if path.stat().st_size != entry['bytes'] or file_sha(path) != entry['sha256']:
            raise ValueError('catalog checksum')
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, 'Die Lizenzdatei stimmt nicht mit dem veröffentlichten Paketnachweis überein.') from None
    return FileResponse(path, filename=path.name, media_type='application/octet-stream',
        headers={'Cache-Control': 'public, max-age=300', 'X-Content-Type-Options': 'nosniff'})
