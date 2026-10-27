"""Account-backed providers are optional; local analysis never requires a cloud login."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import threading
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from ..config import settings
from ..paths import get_data_dir
from . import assistant_provider_vault as vault
from .assistant_provider_prompt import user_payload
from .assistant_provider_protocol import ProviderError

_lock = threading.RLock()
_logins: dict[tuple[str, str, str], dict] = {}
LABELS = {'local': 'Lokale Analyse', 'codex': 'ChatGPT', 'claude': 'Claude'}
DEFAULT_MODELS = {'codex': [{'id': 'gpt-6.1-sol', 'label': 'GPT-6.1 Sol'}],
                  'claude': [{'id': 'sonnet', 'label': 'Sonnet'}, {'id': 'opus', 'label': 'Opus'}]}


def _identity(actor_id, provider):
    if provider not in LABELS:
        raise ProviderError('Dieser KI-Zugang wird nicht unterstützt.', 'unsupported_provider')
    return str(get_data_dir().resolve()), vault.actor_key(actor_id), provider


def executable(provider: str) -> list[str] | None:
    configured = getattr(settings, 'assistant_' + provider + '_cli', '')
    if configured:
        path = Path(configured).expanduser().resolve()
        return [str(path)] if path.is_file() else None
    local = Path(os.environ.get('LOCALAPPDATA', ''))
    patterns = {'codex': local / 'OpenAI/Codex/bin/*/codex.exe',
                'claude': local / 'Programs/ImmoManagerPro/tools/claude-code-*/node_modules/@anthropic-ai/claude-code-win32-x64/claude.exe'}
    if os.name == 'nt' and provider in patterns:
        import glob
        candidates = [Path(path) for path in glob.glob(str(patterns[provider])) if Path(path).is_file()]
        if candidates:
            return [str(max(candidates, key=lambda path: path.stat().st_mtime_ns))]
    found = shutil.which('codex' if provider == 'codex' else 'claude')
    if found and (os.name != 'nt' or Path(found).suffix.lower() == '.exe'):
        return [found]
    return None


def _adapter(provider):
    if provider == 'codex':
        from . import assistant_provider_codex
        return assistant_provider_codex
    from . import assistant_provider_claude
    return assistant_provider_claude


def connection_status(actor_id: str, provider: str) -> dict:
    key = _identity(actor_id, provider)
    if provider == 'local':
        return {'provider': provider, 'connected': True, 'status': 'connected', 'models': [], 'pending_login': None,
                'client_available': True, 'model_discovery_status': 'unknown', 'auth_probe_status': 'verified',
                'account_access_verified_by_inference': False,
                'reason': 'Lokale Regeln, Dokumentextraktion und geprüfte Rechenmodule. Kein Konto und kein Modelldownload erforderlich.'}
    cli = executable(provider)
    reason = None
    try:
        stored = vault.load(actor_id, provider)
        public = stored['public']
        connected = bool(stored['files']) and public.get('connected') is True
    except ProviderError as error:
        public, connected, reason = {}, False, str(error)
    with _lock:
        job = _logins.get(key)
        pending = dict(job['public']) if job else None
        if job and not job['thread'].is_alive() and job['expires'] < time.monotonic():
            _logins.pop(key, None)
            pending = None
    status = 'connected' if connected else 'disconnected'
    if not cli:
        status, connected = 'unavailable', False
        reason = ('Codex CLI' if provider == 'codex' else 'Claude Code') + ' ist auf dem Anwendungsserver nicht installiert. Den offiziellen Client installieren oder den Pfad in der Serverkonfiguration angeben.'
    elif pending and pending['status'] not in {'completed', 'cancelled', 'failed', 'expired'}:
        status = 'connecting'
    elif reason:
        status = 'error'
    return {'provider': provider, 'connected': connected, 'status': status, 'reason': reason,
            'pending_login': pending, 'models': public.get('models') or DEFAULT_MODELS[provider],
            'client_available': bool(cli), 'model_discovery_status': public.get('model_discovery_status', 'unknown'),
            'model_catalog_source': 'account_client' if public.get('model_discovery_status') == 'verified' else 'unverified_defaults',
            'auth_probe_status': public.get('auth_probe_status', 'unknown'), 'auth_checked_at': public.get('auth_checked_at'),
            'auth_mode': public.get('auth_mode'), 'authenticated_at': public.get('authenticated_at'),
            'account_access_verified_by_inference': public.get('account_access_verified_by_inference') is True}


def probe_connection(actor_id: str, provider: str) -> dict:
    """Explicit native auth/catalog check; never starts a model turn or login."""
    _identity(actor_id, provider)
    if provider == 'local':
        return connection_status(actor_id, provider)
    cli = executable(provider)
    if not cli:
        raise ProviderError('Der offizielle Kontoclient ist nicht verfügbar.', 'client_unavailable')
    with vault.ProfileLease(actor_id, provider) as profile:
        public = dict(profile.state['public'])
        try:
            info = _adapter(provider).status(profile, cli, lambda: False)
            public.update(info, auth_checked_at=time.time(), auth_probe_status='verified' if info.get('connected') else 'disconnected')
            if provider == 'claude':
                # Claude's native auth status has no account model catalog.
                public['model_discovery_status'] = 'unavailable'
            if not info.get('connected'):
                public.update(account_access_verified_by_inference=False, models=[], model_discovery_status='unknown')
            profile.save(public)
        except ProviderError as error:
            public.update(auth_checked_at=time.time(), auth_probe_status='error')
            if error.code == 'authentication_required':
                public.update(connected=False, account_access_verified_by_inference=False)
            profile.save(public)
            raise
    return connection_status(actor_id, provider)


def capabilities(actor_id: str) -> dict:
    providers = []
    for provider, label in LABELS.items():
        state = connection_status(actor_id, provider)
        providers.append({'id': provider, 'label': label, 'available': state['status'] != 'unavailable',
                          **state, 'web_research': provider != 'local', 'images': provider != 'local',
                          'documents': True, 'finance_source_budget': 200 if provider != 'local' else None})
    return {'providers': providers, 'api_key_required': False, 'local_reports_independent': True,
            'credentials': 'Encrypted per-application-user account vault; provider manages login and refresh.',
            'finance_source_budget': 200}


def start_login(actor_id: str, provider: str) -> dict:
    key = _identity(actor_id, provider)
    if provider == 'local':
        return connection_status(actor_id, provider)
    cli = executable(provider)
    if not cli:
        raise ProviderError('Der benötigte Kontoclient ist noch nicht installiert.', 'client_unavailable')
    with _lock:
        previous = _logins.get(key)
        if previous and previous['thread'].is_alive():
            return connection_status(actor_id, provider)
        job: dict = {'public': {'id': str(uuid4()), 'status': 'starting', 'can_submit_code': False},
               'cancelled': threading.Event(), 'codes': queue.Queue(), 'expires': time.monotonic() + 600}

        def emit_state(update):
            # Only documented public login fields cross into the application API.
            aliases = {'state': 'status', 'authorization_url': 'auth_url'}
            allowed = {'status', 'verification_url', 'auth_url', 'user_code', 'can_submit_code', 'message'}
            safe = {aliases.get(name, name): value for name, value in update.items() if aliases.get(name, name) in allowed}
            with _lock:
                job['public'].update(safe)

        def perform():
            try:
                with vault.ProfileLease(actor_id, provider, restore=False) as profile:
                    info = _adapter(provider).login(profile, cli, emit_state, job['cancelled'].is_set, job['codes'])
                    if job['cancelled'].is_set():
                        raise ProviderError('Die Anmeldung wurde abgebrochen.', 'cancelled')
                    profile.save({**info, 'connected': True, 'authenticated_at': time.time(),
                                  'auth_checked_at': time.time(), 'auth_probe_status': 'verified',
                                  'model_discovery_status': info.get('model_discovery_status', 'unavailable'),
                                  'account_access_verified_by_inference': False})
                with _lock:
                    job['public'] = {'id': job['public']['id'], 'status': 'completed', 'can_submit_code': False}
            except ProviderError as error:
                with _lock:
                    job['public'] = {'id': job['public']['id'], 'status': 'cancelled' if error.code == 'cancelled' else 'failed',
                                     'error': str(error), 'code': error.code, 'can_submit_code': False}
            except Exception:
                with _lock:
                    job['public'] = {'id': job['public']['id'], 'status': 'failed', 'error': 'Die Anmeldung konnte nicht abgeschlossen werden. Den Kontoclient und den geschützten Speicher prüfen.', 'can_submit_code': False}
            finally:
                while not job['codes'].empty():
                    try:
                        job['codes'].get_nowait()
                    except queue.Empty:
                        break
                job['expires'] = time.monotonic() + 300

        job['thread'] = threading.Thread(target=perform, name='assistant-account-login', daemon=True)
        _logins[key] = job
        job['thread'].start()
    return connection_status(actor_id, provider)


def cancel_login(actor_id: str, provider: str, login_id: str) -> dict:
    key = _identity(actor_id, provider)
    with _lock:
        job = _logins.get(key)
        if job and job['public']['id'] == login_id:
            job['cancelled'].set()
            if job['thread'].is_alive():
                job['public'] = {'id': login_id, 'status': 'cancelling', 'can_submit_code': False}
        elif job:
            raise ProviderError('Die Anmeldesitzung hat sich geändert. Bitte den Status neu laden.', 'login_changed')
    return connection_status(actor_id, provider)


def complete_login(actor_id: str, provider: str, login_id: str, code: str) -> dict:
    key = _identity(actor_id, provider)
    if provider != 'claude' or not isinstance(code, str) or not code.strip() or len(code) > 4096 or '\n' in code or '\r' in code:
        raise ProviderError('Bitte einen gültigen einmaligen Anmeldecode eingeben.', 'invalid_login_code')
    with _lock:
        job = _logins.get(key)
        if not job or job['public']['id'] != login_id or not job['thread'].is_alive() or not job['public'].get('can_submit_code'):
            raise ProviderError('Diese Anmeldesitzung wartet nicht auf einen Code. Bitte neu verbinden.', 'login_changed')
        digest = hashlib.sha256(code.strip().encode()).hexdigest()
        if job.get('code_digest') != digest:
            job['code_digest'] = digest
            job['codes'].put(code.strip())
    return connection_status(actor_id, provider)


def disconnect(actor_id: str, provider: str) -> dict:
    key = _identity(actor_id, provider)
    if provider == 'local':
        return connection_status(actor_id, provider)
    with _lock:
        job = _logins.get(key)
        if job and job['thread'].is_alive():
            job['cancelled'].set()
    if job and job['thread'].is_alive():
        job['thread'].join(timeout=5)
        if job['thread'].is_alive():
            raise ProviderError('Die Anmeldung wird noch beendet. Anschließend erneut trennen.', 'provider_busy')
    vault.disconnect(actor_id, provider)
    with _lock:
        _logins.pop(key, None)
    return connection_status(actor_id, provider)


def _money(value, currency):
    number = Decimal(str(value))
    return f'{number:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.') + ' ' + currency


def _table(headers, rows):
    def cell(value):
        return str(value).replace('|', '/').replace('\n', ' ')
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |',
                      *['| ' + ' | '.join(cell(value) for value in row) + ' |' for row in rows]])


def _local_answer(request):
    analysis = request.get('local_analysis') or {}
    sources = (analysis.get('context') or request.get('context') or {}).get('sources', [])
    lines = ['## Lokale Analyse', 'Diese Auswertung verwendet lokale Regeln und die vorhandenen Rechenmodule. Es wurde kein KI-Anbieter aufgerufen.']
    if sources:
        lines += ['', '### Ausgewählte Quellen']
        for source in sources:
            label = str(source.get('label') or source.get('title') or source['kind'] + ' ' + source['id']).replace('[', '').replace(']', '')
            lines.append('- [' + label + '](' + source.get('href', '') + ')')
    finance = analysis.get('finance')
    if finance:
        currency = finance.get('currency', 'EUR')
        titles = {'cash-v2': 'Zahlungsübersicht', 'performance-period-v2': 'Periodenergebnis', 'liquidity-v2': 'Liquiditätsprognose'}
        labels = {'income': 'Einnahmen', 'expense': 'Ausgaben', 'net': 'Ergebnis', 'balance': 'Kontostand',
                  'rent': 'Mieterlöse', 'other_income': 'Weitere Erträge', 'cost': 'Kosten',
                  'interest': 'Zinsen', 'depreciation': 'Abschreibung', 'result': 'Periodenergebnis'}
        selected = finance['filters']
        period = ' bis '.join(str(selected[key]) for key in ('date_from', 'date_to') if selected.get(key))
        lines += ['', '### ' + titles.get(finance['basis'], 'Geprüfte Finanzwerte'),
                  'Zeitraum: ' + (period or 'gemäß gewählter Definition') + ' · Währung: ' + currency]
        totals = finance.get('totals') or {}
        if totals:
            lines.append(_table(['Kennzahl', 'Betrag'], [(labels.get(key, key), _money(value, currency)) for key, value in totals.items()]))
        if 'opening_balance' in finance:
            lines.append(_table(['Kennzahl', 'Betrag'], [('Anfangsbestand', _money(finance['opening_balance'], currency)),
                                                      ('Endbestand', _money(finance['closing_balance'], currency))]))
        monthly = finance.get('monthly') or []
        if monthly:
            columns = [key for key in monthly[0] if key != 'month']
            lines += ['### Monatsverlauf', _table(['Monat', *[labels.get(key, key) for key in columns]],
                       [(row['month'], *[_money(row[key], currency) for key in columns]) for row in monthly])]
        lines += ['Quellbelege: ' + str(len(finance.get('sources') or [])) + '. Die verwendeten Quellen und die genaue Auswahl sind unter dieser Antwort verknüpft.',
                  'Ergebnisprüfung: `' + finance['result_hash'] + '`.']
        lines.extend('- ' + str(item.get('message') or item) for item in finance.get('warnings') or [])
    findings = analysis.get('findings') or []
    lines += ['', '### Angaben prüfen']
    lines.extend('- ' + item['message'] for item in findings)
    if not findings:
        lines.append('Die durchgeführten lokalen Regeln haben in der gewählten Auswahl keine Hinweise gefunden. Das ist keine vollständige fachliche Freigabe.')
    for document in analysis.get('documents') or []:
        source = document.get('source') or {}
        lines += ['### Dokument ' + source.get('id', ''), str(document.get('summary') or 'Lokal extrahierter Dokumenttext verfügbar.')]
        fields = [(label, document[key]) for key, label in (('document_type', 'Dokumentart'), ('supplier', 'Aussteller'),
                  ('invoice_number', 'Rechnungsnummer'), ('invoice_date', 'Rechnungsdatum'), ('total_amount', 'Erkannter Betrag')) if document.get(key) is not None]
        if fields:
            lines.append(_table(['Erkanntes Feld', 'Ungeprüfter Vorschlag'], fields))
        lines.append('Die automatische Texterkennung ist ein Vorschlag. Original und Werte vor einer Übernahme prüfen.')
        if document.get('text'):
            lines.append(document['text'])
        lines.extend('- ' + value for value in document.get('omissions') or [])
    for attachment in request.get('attachments', []):
        lines += ['', '### ' + str(attachment['name']), attachment.get('text') or 'Für diese Datei liegt kein lokal extrahierbarer Text vor.']
        lines.extend('- ' + str(value) for value in attachment.get('omissions') or [])
    if not sources and not request.get('attachments'):
        lines += ['', 'Wählen Sie Akten oder Dateien aus. Finanzübersichten und Statistiken stehen im Bereich [Auswertungen](/reports) vollständig lokal bereit. Ein freier Dialog mit einem Sprachmodell ist über ChatGPT oder Claude möglich.']
    return {'text': '\n\n'.join(lines), 'proposals': [], 'usage': {'mode': 'local', 'model_used': False}}


def execute(actor_id: str, provider: str, request: dict, emit, cancelled) -> dict:
    _identity(actor_id, provider)
    if cancelled():
        raise ProviderError('Die Antwort wurde abgebrochen.', 'cancelled')
    if provider == 'local':
        if request.get('web_research'):
            raise ProviderError('Internetrecherche benötigt einen verbundenen KI-Anbieter.', 'unsupported_feature')
        result = _local_answer(request)
        emit({'type': 'delta', 'text': result['text']})
        return result
    cli = executable(provider)
    if not cli:
        raise ProviderError('Der Kontoclient ist nicht installiert. Lokale Analyse ist weiterhin verfügbar.', 'client_unavailable')
    payload = json.loads(user_payload(request))
    for omission in payload.get('omissions', []):
        emit({'type': 'status', 'message': omission})
    with vault.ProfileLease(actor_id, provider) as profile:
        if not profile.state['files']:
            raise ProviderError('Bitte zuerst das ' + LABELS[provider] + '-Konto verbinden.', 'authentication_required')
        try:
            result = _adapter(provider).execute(profile, cli, request, emit, cancelled)
            profile.save({**profile.state['public'], 'connected': True, 'account_access_verified_by_inference': True,
                          'last_inference_at': time.time()})
            return result
        except ProviderError as error:
            public = dict(profile.state['public'])
            if error.code == 'authentication_required':
                public['connected'] = False
                public['account_access_verified_by_inference'] = False
            profile.save(public)
            raise
