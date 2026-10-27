"""Official Codex app-server account flow and ephemeral, restricted inference turns."""
from __future__ import annotations

import base64
import json
import time
from collections import deque

from .assistant_provider_process import CliProcess
from .assistant_provider_prompt import checked_model, finish_answer, system_prompt, user_payload
from .assistant_provider_protocol import ProviderError, application_mcp
from .secret_box import write_private_file


def public_error(error, *, uncertain=False):
    message = json.dumps(error, default=str).lower()
    if any(value in message for value in ("unauthorized", "unauthenticated", "401", "login", "authentication")):
        return ProviderError("Die ChatGPT-Anmeldung muss erneuert werden. Bitte das Konto verbinden.", "authentication_required", uncertain=uncertain)
    if any(value in message for value in ("rate limit", "429", "quota", "usage limit")):
        return ProviderError("Das Nutzungskontingent des ChatGPT-Kontos ist erreicht. Später erneut versuchen oder lokale Analyse wählen.", "rate_limited", uncertain=uncertain)
    if "context" in message and any(value in message for value in ("limit", "length", "large")):
        return ProviderError("Die Auswahl ist für dieses Modell zu umfangreich. Dateien oder Verlauf eingrenzen und erneut senden.", "context_too_large", uncertain=uncertain)
    if "model" in message and any(value in message for value in ("available", "support", "access", "found")):
        return ProviderError("Das gewählte Modell ist mit diesem Konto nicht verfügbar. Bitte ein anderes Modell wählen.", "model_unavailable", uncertain=uncertain)
    if 'timed out' in message or 'timeout' in message:
        return ProviderError('Die KI-Verbindung hat das Zeitlimit erreicht. Bitte den Ergebnisstatus prüfen und bei Bedarf bewusst erneut versuchen.', 'provider_timeout', uncertain=True)
    if isinstance(error, dict) and error.get('code') in (-32600, -32601, -32602):
        return ProviderError('Der installierte Codex-Client unterstützt das benötigte Protokoll nicht. Bitte die KI-Verbindung und Clientversion prüfen.', 'protocol_incompatible', uncertain=uncertain)
    return ProviderError("ChatGPT konnte den Vorgang nicht abschließen. Bitte den Ergebnisstatus prüfen und anschließend erneut versuchen.", "provider_error", uncertain=uncertain)


class CodexRpc:
    def __init__(self, profile, executable, *, research=False, mcp=None):
        self.profile = profile
        self.counter = 0
        self.events: deque[dict] = deque()
        self.responses = {}
        config = ('cli_auth_credentials_store = "file"\n'
                  'forced_login_method = "chatgpt"\n'
                  'check_for_update_on_startup = false\n'
                  'history.persistence = "none"\n'
                  'project_doc_max_bytes = 0\n'
                  'features.shell_tool = false\n'
                  'features.shell_snapshot = false\n'
                  'features.apps = false\n'
                  'features.plugins = false\n'
                  'tools.view_image = false\n'
                  'apps._default.enabled = false\n'
                  'mcp_servers = {}\n'
                  + 'web_search = ' + ('"live"' if research else '"disabled"') + '\n'
                  # Restricted reads now use named permission profiles. Do not
                  # send a legacy sandbox override that would replace this
                  # profile with filesystem-wide read access.
                  'default_permissions = "immomanager"\n'
                  '\n[permissions.immomanager.filesystem]\n'
                  '":root" = "deny"\n'
                  + json.dumps(str(profile.path / 'work')) + ' = "read"\n'
                  '\n[permissions.immomanager.network]\n'
                  'enabled = false\n')
        if mcp is not None:
            config = config.replace('mcp_servers = {}\n', '')
            config += ('\n[mcp_servers.immomanager]\nurl = ' + json.dumps(mcp['url'])
                       + '\nenabled = true\nrequired = true\nenabled_tools = ' + json.dumps(mcp['tools'])
                       + '\ndefault_tools_approval_mode = "approve"\nhttp_headers = '
                       + '{ Authorization = ' + json.dumps(mcp['headers']['Authorization']) + ' }\n')
        write_private_file(profile.path / 'config.toml', config.encode())
        self.transport = CliProcess([*executable, 'app-server', '--listen', 'stdio://'], profile.path)
        try:
            self.call('initialize', {'clientInfo': {'name': 'immomanager_pro', 'title': 'ImmoManager Pro', 'version': '1'},
                                     'capabilities': {'experimentalApi': True}}, timeout=20)
            self.transport.write_line(json.dumps({'method': 'initialized', 'params': {}}))
        except BaseException:
            self.close()
            raise

    def _read(self, timeout=.2):
        value = self.transport.next_line(timeout)
        if value is None:
            if self.transport.process.poll() is not None:
                raise ProviderError('Die Verbindung zu Codex wurde beendet.', 'process_closed', uncertain=True)
            return
        channel, line = value
        if channel != 'stdout':
            return
        try:
            data = json.loads(line)
        except (ValueError, RecursionError) as error:
            raise ProviderError('Die installierte Codex-Version liefert kein unterstütztes Protokoll.', 'protocol_incompatible', uncertain=True) from error
        if (not isinstance(data, dict) or
                ('id' in data and (isinstance(data['id'], bool) or not isinstance(data['id'], (int, str)))) or
                ('method' in data and not isinstance(data['method'], str)) or
                ('params' in data and not isinstance(data['params'], dict))):
            raise ProviderError('Die installierte Codex-Version liefert kein unterstütztes Protokoll.', 'protocol_incompatible', uncertain=True)
        if 'method' in data:
            if 'id' in data:
                # No provider request can authorize filesystem, process, MCP or credential access.
                self.transport.write_line(json.dumps({'id': data['id'], 'error': {'code': -32601, 'message': 'Not supported by ImmoManager'}}))
            else:
                self.events.append(data)
        elif 'id' in data:
            self.responses[data['id']] = data

    def call(self, method, params=None, *, timeout=30):
        self.counter += 1
        key = self.counter
        self.transport.write_line(json.dumps({'id': key, 'method': method, 'params': params or {}}, ensure_ascii=False))
        deadline = time.monotonic() + timeout
        while key not in self.responses:
            if time.monotonic() > deadline:
                raise ProviderError('Codex antwortet noch nicht. Bitte den Ergebnisstatus prüfen.', 'provider_timeout', uncertain=True)
            self._read()
        data = self.responses.pop(key)
        if data.get('error'):
            raise public_error(data['error'])
        result = data.get('result', {})
        if not isinstance(result, dict):
            raise ProviderError('Die installierte Codex-Version liefert kein unterstütztes Ergebnis.', 'protocol_incompatible', uncertain=True)
        return result

    def event(self, timeout=.2):
        if not self.events:
            self._read(timeout)
        return self.events.popleft() if self.events else None

    def close(self):
        self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _models(rpc):
    models, cursor, seen = [], None, set()
    while True:
        result = rpc.call('model/list', {'limit': 100, **({'cursor': cursor} if cursor else {})})
        for item in result.get('data', []):
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                continue
            model: dict = {'id': item['id'], 'label': item.get('displayName') or item['id']}
            efforts = item.get('supportedReasoningEfforts')
            if isinstance(efforts, list):
                model['supported_efforts'] = [entry['reasoningEffort'] for entry in efforts if isinstance(entry, dict)
                                              and entry.get('reasoningEffort') in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}]
            if isinstance(item.get('inputModalities'), list):
                model['input_modalities'] = [value for value in item['inputModalities'] if value in {'text', 'image'}]
            models.append(model)
        cursor = result.get('nextCursor')
        if not cursor:
            return models
        if not isinstance(cursor, str) or cursor in seen:
            raise ProviderError('Der Modellkatalog konnte nicht vollständig geprüft werden.', 'protocol_incompatible')
        seen.add(cursor)


def status(profile, executable, cancelled):
    if cancelled():
        raise ProviderError('Die Kontoprüfung wurde abgebrochen.', 'cancelled')
    with CodexRpc(profile, executable) as rpc:
        account = rpc.call('account/read', {'refreshToken': False}).get('account') or {}
        connected = account.get('type') == 'chatgpt'
        result = {'connected': connected, 'auth_mode': 'chatgpt' if connected else 'none', 'model_discovery_status': 'unknown'}
        if connected:
            try:
                result['models'] = _models(rpc)
                result['model_discovery_status'] = 'verified' if result['models'] else 'unavailable'
            except ProviderError:
                result['model_discovery_status'] = 'unavailable'
        return result


def _check_mcp(rpc, thread_id, mcp):
    inventory = rpc.call('mcpServerStatus/list', {'threadId': thread_id, 'detail': 'toolsAndAuthOnly', 'limit': 100})
    servers = inventory.get('data')
    if (not isinstance(servers, list) or len(servers) != 1 or inventory.get('nextCursor')
            or not isinstance(servers[0], dict) or servers[0].get('name') != 'immomanager'
            or servers[0].get('httpOrigin') != mcp['url'].removesuffix('/mcp')
            or servers[0].get('runtimeStatus') != 'connected' or servers[0].get('toolsError') or servers[0].get('pluginId')
            or not isinstance(servers[0].get('tools'), dict) or set(servers[0]['tools']) != set(mcp['tools'])):
        raise ProviderError('Die Anwendung konnte ihre geschützten Werkzeuge nicht vollständig verbinden.', 'provider_isolation_failed')


def login(profile, executable, emit_state, cancelled, codes):
    if cancelled():
        raise ProviderError('Die Anmeldung wurde abgebrochen.', 'cancelled')
    with CodexRpc(profile, executable) as rpc:
        started = rpc.call('account/login/start', {'type': 'chatgptDeviceCode'})
        if started.get('type') != 'chatgptDeviceCode' or not started.get('loginId'):
            raise ProviderError('Diese Codex-Version unterstützt die benötigte Kontoanmeldung nicht.', 'protocol_incompatible')
        url = started.get('verificationUrl', '')
        from urllib.parse import urlparse
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError:
            port = -1
        if (parsed.scheme != 'https' or parsed.hostname not in {'auth.openai.com', 'chatgpt.com'} or
                parsed.username or parsed.password or port not in (None, 443) or parsed.fragment or parsed.query):
            raise ProviderError('Codex hat keine gültige Anmeldeseite geliefert.', 'protocol_incompatible')
        emit_state({'status': 'awaiting_authorization', 'verification_url': url, 'user_code': started.get('userCode'),
                    'can_submit_code': False})
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if cancelled():
                try:
                    rpc.call('account/login/cancel', {'loginId': started['loginId']}, timeout=5)
                finally:
                    raise ProviderError('Die Anmeldung wurde abgebrochen.', 'cancelled')
            event = rpc.event()
            if event and event.get('method') == 'account/login/completed':
                params = event.get('params', {})
                if params.get('loginId') != started['loginId']:
                    continue
                if not params.get('success'):
                    raise ProviderError('Die Anmeldung wurde nicht abgeschlossen. Bitte erneut verbinden.', 'authentication_required')
                account = rpc.call('account/read', {'refreshToken': False}).get('account') or {}
                if account.get('type') != 'chatgpt':
                    raise ProviderError('Bitte mit einem ChatGPT-Konto anmelden.', 'authentication_required')
                info = {'connected': True, 'auth_mode': 'chatgpt'}
                try:
                    info['models'] = _models(rpc)
                    info['model_discovery_status'] = 'verified' if info['models'] else 'unavailable'
                except ProviderError:
                    # Authentication and catalog discovery are independent.
                    # Preserve a successful login when the catalog is offline.
                    info['model_discovery_status'] = 'unavailable'
                return info
        raise ProviderError('Die Anmeldezeit ist abgelaufen. Bitte erneut verbinden.', 'login_expired')


def execute(profile, executable, request, emit, cancelled):
    if cancelled():
        raise ProviderError('Die Antwort wurde abgebrochen.', 'cancelled')
    mcp = application_mcp(request)
    rpc_options: dict = {'research': bool(request.get('web_research'))}
    if mcp:
        rpc_options['mcp'] = mcp
    with CodexRpc(profile, executable, **rpc_options) as rpc:
        account = rpc.call('account/read', {'refreshToken': True}).get('account') or {}
        if account.get('type') != 'chatgpt':
            raise ProviderError('Bitte zuerst das ChatGPT-Konto verbinden.', 'authentication_required')
        model = checked_model(request.get('model'))
        work = profile.path / 'work'
        params = {'cwd': str(work), 'approvalPolicy': 'never', 'permissions': 'immomanager', 'ephemeral': True,
                  'baseInstructions': system_prompt(request), 'developerInstructions': 'Only the explicitly configured immomanager MCP tools are allowed. No shell, filesystem tools, apps, plugins or external conversation history.',
                  'model': model}
        started = rpc.call('thread/start', params)
        active = started.get('activePermissionProfile')
        if not isinstance(active, dict) or active.get('id') != 'immomanager' or active.get('extends'):
            raise ProviderError('Der Kontoclient hat das private Berechtigungsprofil nicht bestätigt.', 'provider_isolation_failed')
        thread = started.get('thread', {})
        if not thread.get('id'):
            raise ProviderError('Codex konnte das Gespräch nicht beginnen.', 'protocol_incompatible')
        if mcp:
            _check_mcp(rpc, thread['id'], mcp)
        inputs = [{'type': 'text', 'text': user_payload(request)}]
        image_types = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
        for index, attachment in enumerate(request.get('attachments', [])):
            if not attachment.get('data_base64'):
                continue
            if attachment.get('mime') not in image_types:
                raise ProviderError('Dieses Bildformat wird von ChatGPT nicht unterstützt.', 'unsupported_attachment')
            image = work / ('image-' + str(index) + image_types[attachment['mime']])
            try:
                content = base64.b64decode(attachment['data_base64'], validate=True)
            except (ValueError, TypeError) as error:
                raise ProviderError('Die Bildanlage ist beschädigt.', 'invalid_attachment') from error
            write_private_file(image, content)
            inputs.append({'type': 'localImage', 'path': str(image)})
        if cancelled():
            raise ProviderError('Die Antwort wurde abgebrochen.', 'cancelled')
        turn = rpc.call('turn/start', {'threadId': thread['id'], 'input': inputs, 'model': model,
                        'effort': request.get('effort') or 'high', 'approvalPolicy': 'never',
                        'permissions': 'immomanager'}).get('turn', {})
        if not turn.get('id'):
            raise ProviderError('Der Ergebnisstatus der Anfrage ist unklar. Bitte prüfen.', 'unknown_result', uncertain=True)
        finals: dict[str, dict] = {}
        deltas: dict[str, str] = {}
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if cancelled():
                try:
                    rpc.call('turn/interrupt', {'threadId': thread['id'], 'turnId': turn['id']}, timeout=5)
                finally:
                    raise ProviderError('Die Antwort wurde abgebrochen.', 'cancelled', uncertain=True)
            event = rpc.event()
            if not event:
                continue
            params = event.get('params', {})
            method = event.get('method')
            if params.get('threadId') not in (None, thread['id']):
                continue
            if params.get('turnId') not in (None, turn['id']):
                continue
            if method in ('item/started', 'item/completed'):
                item = params.get('item')
                if not isinstance(item, dict):
                    raise ProviderError('Codex hat einen ungültigen Antwortabschnitt geliefert.', 'protocol_incompatible', uncertain=True)
                forbidden = {'commandExecution', 'fileChange', 'dynamicToolCall', 'collabAgentToolCall', 'imageView'}
                if item.get('type') == 'mcpToolCall' and (not mcp or item.get('server') != 'immomanager' or item.get('tool') not in mcp['tools'] or item.get('pluginId')):
                    raise ProviderError('Der Kontoclient hat ein nicht freigegebenes Werkzeug angefordert. Der Lauf wurde beendet.', 'unexpected_tool', uncertain=True)
                if item.get('type') in forbidden or (item.get('type') == 'webSearch' and not request.get('web_research')):
                    raise ProviderError('Der Kontoclient hat ein nicht freigegebenes Werkzeug angefordert. Der Lauf wurde beendet.', 'unexpected_tool', uncertain=True)
            if method == 'item/agentMessage/delta':
                value = params.get('delta')
                if isinstance(value, str):
                    item_id = params.get('itemId', 'answer')
                    deltas[item_id] = deltas.get(item_id, '') + value
                    emit({'type': 'delta', 'text': value})
            elif method == 'item/completed':
                item = params.get('item', {})
                if item.get('type') == 'agentMessage':
                    finals[item.get('id', 'answer')] = item
            elif method == 'turn/completed':
                completed = params.get('turn', {})
                if completed.get('id') != turn['id']:
                    continue
                if completed.get('status') != 'completed':
                    raise public_error(completed.get('error') or completed.get('status'))
                chosen = [item['text'] for item in finals.values() if item.get('phase') == 'final_answer' and item.get('text')]
                if not chosen:
                    chosen = [item['text'] for item in finals.values() if item.get('text')] or list(deltas.values())
                text = '\n\n'.join(chosen)
                if not text.strip():
                    raise ProviderError('ChatGPT lieferte keine verwertbare Antwort. Bitte die Anfrage prüfen.', 'empty_answer')
                return {**finish_answer(text), 'provider_session_id': thread['id'], 'provider_turn_id': turn['id']}
        raise ProviderError('Die Antwort dauert länger als dieses Arbeitspaket. Der externe Ausgang ist unklar; bitte den Lauf prüfen.', 'provider_timeout', uncertain=True)
