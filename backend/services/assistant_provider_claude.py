"""Account-backed Claude CLI transport in a private, tool-restricted profile.

Protocol references: https://code.claude.com/docs/en/headless and
https://code.claude.com/docs/en/agent-sdk/streaming-output. CLI flags were
verified against the privately installed 2.1.302 native executable's help.
This adapter never persists credentials, resumes a CLI session, or executes
model-proposed host actions. Vault and application transactions belong to the hub.
"""

from __future__ import annotations

import base64
import json
import queue
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .assistant_provider_process import CliProcess, private_environment
from .assistant_provider_prompt import checked_model, finish_answer, system_prompt, user_payload
from .assistant_provider_protocol import ProviderError, application_mcp
from .assistant_provider_vault import ProfileLease
from .secret_box import write_private_file

LOGIN_TIMEOUT = 600
STATUS_TIMEOUT = 30
EXECUTE_TIMEOUT = 900
MAX_OUTPUT_CHARS = 2_000_000
AUTH_HOSTS = frozenset({"claude.ai", "claude.com", "console.anthropic.com", "platform.claude.com",
                        "accounts.anthropic.com", "auth.anthropic.com"})
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
URL = re.compile(r"https://[^\s<>\"'\x00-\x1f]+")


def _path(profile: ProfileLease) -> Path:
    if profile.provider != "claude" or profile.path is None:
        raise ProviderError("Der private Claude-Zugang ist nicht verfügbar.", "credentials_unavailable")
    return profile.path


def _auth_url(line: str) -> str | None:
    for match in URL.finditer(ANSI.sub("", line)):
        candidate = match.group().rstrip(".,;)")
        if len(candidate) > 8192:
            continue
        try:
            parsed = urlsplit(candidate)
            if (parsed.scheme != "https" or parsed.hostname not in AUTH_HOSTS or parsed.username
                    or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
                continue
            if not any(part in parsed.path.lower() for part in ("oauth", "authorize", "login")):
                continue
            sensitive = {"access_token", "refresh_token", "id_token", "api_key", "password", "client_secret", "secret", "token"}
            if any(key.lower() in sensitive for key, _ in parse_qsl(parsed.query)):
                continue
        except ValueError:
            continue
        return candidate
    return None


def _cancel(cancelled: Callable[[], bool], *, submitted: bool = False) -> None:
    if cancelled():
        raise ProviderError("Der KI-Vorgang wurde abgebrochen.", "cancelled", uncertain=submitted)


def _events(process: CliProcess, cancelled: Callable[[], bool], timeout: int, *, submitted: bool = False):
    deadline = time.monotonic() + timeout
    closed: set[str] = set()
    while True:
        _cancel(cancelled, submitted=submitted)
        if time.monotonic() >= deadline:
            raise ProviderError("Der KI-Vorgang hat das Zeitlimit erreicht. Bitte den Ergebnisstatus prüfen.",
                                "provider_timeout", uncertain=submitted)
        item = process.next_line(timeout=.2)
        if item is not None:
            channel, line = item
            if channel.endswith("_closed"):
                closed.add(channel)
            elif channel in ("stdout", "stderr"):
                yield channel, line
        # Browser descendants can inherit a pipe after the official client
        # exits. Drain buffered lines, then use the client's exit status;
        # waiting for those descendants would discard a successful login.
        if process.process.poll() is not None and (item is None or {"stdout_closed", "stderr_closed"}.issubset(closed)):
            return


def _json(line: str) -> dict | None:
    try:
        value = json.loads(line)
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None


def status(profile: ProfileLease, executable: list[str], cancelled: Callable[[], bool]) -> dict:
    """Never report an API-key/third-party/global account as this user's login."""
    try:
        with CliProcess([*executable, "auth", "status", "--json"], _path(profile)) as process:
            process.close_stdin()
            output: list[str] = []
            size = 0
            for channel, line in _events(process, cancelled, STATUS_TIMEOUT):
                if channel == "stdout":
                    size += len(line)
                    if size > 64_000:
                        raise ProviderError("Der Claude-Anmeldestatus ist nicht lesbar.", "authentication_status_invalid")
                    output.append(line)
            result = _json("".join(output))
            if result is None:
                raise ProviderError("Der Claude-Anmeldestatus ist nicht lesbar.", "authentication_status_invalid")
            connected = (process.process.returncode == 0 and result.get("loggedIn") is True
                         and result.get("authMethod") == "claude.ai"
                         and result.get("apiProvider") == "firstParty")
            public = {"connected": connected, "auth_method": "claude.ai" if connected else "none"}
            if connected and result.get("subscriptionType") in ("pro", "max", "team", "enterprise"):
                public["subscription_type"] = result["subscriptionType"]
            return public
    except (OSError, ValueError) as error:
        raise ProviderError("Die lokale Claude-Anmeldung konnte nicht geprüft werden.", "authentication_status_failed") from error


def login(profile: ProfileLease, executable: list[str], emit_state: Callable[[dict], None],
          cancelled: Callable[[], bool], codes: queue.Queue) -> dict:
    """Only the trusted authorization URL is public; pasted codes go to stdin."""
    _cancel(cancelled)
    try:
        with CliProcess([*executable, "auth", "login", "--claudeai"], _path(profile)) as process:
            authorization_url = None
            code_submitted = False
            deadline = time.monotonic() + LOGIN_TIMEOUT
            closed: set[str] = set()
            while True:
                _cancel(cancelled)
                if time.monotonic() >= deadline:
                    raise ProviderError("Die Claude-Anmeldung ist abgelaufen. Bitte erneut verbinden.", "authentication_timeout")
                item = process.next_line(timeout=.2)
                if item is not None:
                    channel, line = item
                    if channel.endswith("_closed"):
                        closed.add(channel)
                    elif channel in ("stdout", "stderr"):
                        observed = _auth_url(line)
                        if observed and authorization_url != observed:
                            authorization_url = observed
                            code_submitted = False
                            emit_state({"state": "awaiting_code", "authorization_url": observed, "can_submit_code": True,
                                        "message": "Claude im Browser anmelden und den einmaligen Bestätigungscode hier einfügen."})
                if authorization_url and not code_submitted and process.process.poll() is None:
                    try:
                        code = codes.get_nowait()
                    except queue.Empty:
                        code = None
                    if code is not None:
                        if (not isinstance(code, str) or not code.strip() or len(code) > 4096
                                or not re.fullmatch(r"[A-Za-z0-9._~+/#=-]+", code.strip())):
                            raise ProviderError("Der einmalige Anmeldecode ist ungültig. Bitte erneut verbinden.", "invalid_authentication_code")
                        process.write_line(code.strip())
                        code_submitted = True
                        code = None
                        emit_state({"state": "checking", "can_submit_code": False,
                                    "message": "Claude prüft die Anmeldung."})
                if process.process.poll() is not None and (item is None or {"stdout_closed", "stderr_closed"}.issubset(closed)):
                    break
            if process.process.returncode != 0:
                raise ProviderError("Die Claude-Anmeldung wurde nicht bestätigt. Bitte erneut verbinden.", "authentication_failed")
        public = status(profile, executable, cancelled)
        if not public["connected"]:
            raise ProviderError("Claude hat keine bestätigte Claude.ai-Anmeldung für dieses Profil gespeichert.", "authentication_failed")
        return public
    except (OSError, ValueError) as error:
        raise ProviderError("Die lokale Claude-Anmeldung konnte nicht gestartet werden.", "authentication_failed") from error


def _input(request: dict) -> dict:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_payload(request)}]
    for attachment in request.get("attachments", []):
        data = attachment.get("data_base64")
        if data is None:
            continue
        mime = attachment.get("mime")
        if mime not in IMAGE_TYPES or not isinstance(data, str):
            raise ProviderError("Dieses Bildformat kann Claude nicht verarbeiten.", "unsupported_attachment")
        try:
            base64.b64decode(data, validate=True)
        except (ValueError, TypeError) as error:
            raise ProviderError("Die ausgewählten Bilddaten sind beschädigt.", "invalid_attachment") from error
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
    return {"type": "user", "message": {"role": "user", "content": content}}


def _identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value) else None


def _usage(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            if type(value.get(key)) is int and value[key] >= 0}


def _authentication_failed(final: dict) -> bool:
    """Recognize explicit terminal auth failures without exposing provider text.

    A retry notification or a successful answer mentioning login is not an
    authentication verdict. Only the failed final envelope is inspected.
    """
    if final.get("is_error") is not True:
        return False
    codes = {"authentication_error", "authentication_failed", "unauthorized", "oauth_org_not_allowed", "invalid_api_key"}
    fragments: list[str] = []

    def inspect(value):
        if isinstance(value, str):
            fragments.append(value.lower())
        elif isinstance(value, dict):
            for key in ("type", "code", "error", "message"):
                inspect(value.get(key))
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    for key in ("error", "errors", "result"):
        inspect(final.get(key))
    phrases = ("not logged in", "please run /login", "authentication failed", "authentication_error",
               "authentication_failed", "oauth token expired", "oauth token has expired", "invalid oauth token",
               "invalid bearer token", "invalid api key", "unauthorized")
    return any(fragment in codes or any(phrase in fragment for phrase in phrases) for fragment in fragments)


def _init(event: dict, web: bool, mcp=None) -> None:
    tools = event.get("tools")
    permitted = {"WebSearch"} if web else set()
    expected = {"mcp__immomanager__" + tool for tool in mcp['tools']} if mcp else set()
    permitted |= expected
    servers = event.get('mcp_servers') or []
    valid_servers = (not servers if not mcp else isinstance(servers, list) and len(servers) == 1
                     and isinstance(servers[0], dict) and servers[0].get('name') == 'immomanager'
                     and servers[0].get('status') == 'connected')
    if (not isinstance(tools, list) or any(not isinstance(tool, str) or tool not in permitted for tool in tools)
            or not expected.issubset(set(tools)) or not valid_servers or event.get("plugins") or event.get('mcp_server_errors')):
        raise ProviderError("Claude hat unerwartete Werkzeuge oder Erweiterungen geladen. Der Vorgang wurde beendet.",
                            "provider_isolation_failed", uncertain=True)


def execute(profile: ProfileLease, executable: list[str], request: dict, emit: Callable[[dict], None],
            cancelled: Callable[[], bool]) -> dict:
    _cancel(cancelled)
    web = request.get("web_research") is True
    mcp = application_mcp(request)
    permitted = {"WebSearch"} if web else set()
    if mcp:
        permitted.update('mcp__immomanager__' + tool for tool in mcp['tools'])
        config = _path(profile) / 'application-mcp.json'
        write_private_file(config, json.dumps({'mcpServers': {'immomanager': {
            'type': 'http', 'url': mcp['url'], 'headers': mcp['headers']}}}).encode())
        mcp_config = str(config)
    else:
        mcp_config = '{"mcpServers":{}}'
    argv = [*executable, "--print", "--restricted", "--safe-mode", "--strict-mcp-config",
            "--mcp-config", mcp_config, "--setting-sources", "", "--no-chrome",
            "--no-session-persistence", "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--disable-slash-commands", "--tools", "WebSearch" if web else "",
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--system-prompt", system_prompt(request)]
    if permitted:
        argv += ["--allowedTools", ','.join(sorted(permitted))]
    if mcp:
        argv += ['--disallowedTools', 'EndConversation,ToolSearch']
        # Native 2.1.302 blocks even command-line MCP servers in safe mode.
        # Replace that blanket switch with explicit context/hook isolation.
        argv.remove('--safe-mode')
    # Native 2.1.302 enables these bundled plugins after account login, even
    # with installed plugins disabled. Disable them for this invocation; keep
    # rejecting every plugin in the actual init envelope. --bare cannot be
    # used here because that mode intentionally does not read OAuth logins.
    argv += ['--settings', json.dumps({'disableAllHooks': True, 'autoMemoryEnabled': False,
        'enabledPlugins': {'cc-plugin-agents-md@builtin': False,
                           'cc-plugin-plugin-authoring@builtin': False}}, separators=(',', ':'))]
    model = checked_model(request.get("model"))
    if model:
        argv += ["--model", model]
    effort = request.get("effort")
    if effort:
        if effort not in ("low", "medium", "high", "xhigh", "max"):
            raise ProviderError("Diese Claude-Denktiefe wird nicht unterstützt.", "invalid_effort")
        argv += ["--effort", effort]
    payload = json.dumps(_input(request), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # Claude's documented piped-stdin limit; this is a transport budget.
    if len(payload.encode("utf-8")) > 10_000_000:
        raise ProviderError("Das Claude-Verarbeitungspaket überschreitet 10 MB. Bitte weniger Quellen oder Bilder auswählen.", "input_too_large")
    submitted = False
    environment = private_environment(_path(profile))
    environment.update(CLAUDE_CODE_DISABLE_CLAUDE_MDS='1', CLAUDE_CODE_DISABLE_ATTACHMENTS='1',
                       CLAUDE_CODE_DISABLE_POLICY_SKILLS='1', CLAUDE_CODE_DISABLE_BACKGROUND_TASKS='1',
                       CLAUDE_CODE_DISABLE_CRON='1', CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL='1',
                       CLAUDE_CODE_DISABLE_BUNDLED_SKILLS='1', ENABLE_CLAUDEAI_MCP_SERVERS='false',
                       ENABLE_TOOL_SEARCH='false')
    try:
        with CliProcess(argv, _path(profile), env=environment) as process:
            process.write_line(payload)
            submitted = True
            process.close_stdin()
            final = None
            session_id = turn_id = None
            initialized = False
            size = 0
            assistant_text: list[str] = []
            delta_text: list[str] = []
            for channel, line in _events(process, cancelled, EXECUTE_TIMEOUT, submitted=True):
                if channel != "stdout":
                    continue
                event = _json(line)
                if event is None:
                    raise ProviderError("Claude hat eine ungültige Antwort geliefert.", "provider_protocol_error", uncertain=True)
                size += len(line)
                if size > MAX_OUTPUT_CHARS:
                    raise ProviderError("Die Claude-Antwort ist zu groß. Bitte die Anfrage eingrenzen.", "output_too_large", uncertain=True)
                if event.get("parent_tool_use_id"):
                    continue
                event_type = event.get("type")
                if event_type == "system" and event.get("subtype") == "init":
                    _init(event, web, mcp)
                    initialized = True
                    session_id = _identifier(event.get("session_id"))
                elif event_type == "stream_event":
                    stream = event.get("event")
                    if not isinstance(stream, dict):
                        continue
                    if stream.get("type") == "message_start":
                        message = stream.get("message")
                        if isinstance(message, dict):
                            turn_id = _identifier(message.get("id")) or turn_id
                    delta = stream.get("delta")
                    if isinstance(delta, dict) and delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                        if not initialized:
                            raise ProviderError("Der Claude-Startstatus fehlt.", "provider_protocol_error", uncertain=True)
                        delta_text.append(delta["text"])
                        emit({"type": "delta", "text": delta["text"]})
                    block = stream.get("content_block")
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") not in permitted:
                        raise ProviderError("Claude hat ein nicht freigegebenes Werkzeug angefordert.", "provider_isolation_failed", uncertain=True)
                elif event_type == "assistant":
                    message = event.get("message")
                    if isinstance(message, dict):
                        turn_id = _identifier(message.get("id")) or turn_id
                        for block in message.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                                assistant_text.append(block["text"])
                            elif isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") not in permitted:
                                raise ProviderError("Claude hat ein nicht freigegebenes Werkzeug angefordert.", "provider_isolation_failed", uncertain=True)
                elif event_type == "result":
                    final = event
            if final is not None and _authentication_failed(final):
                raise ProviderError("Die Claude-Anmeldung muss erneuert werden. Bitte das Konto erneut verbinden.", "authentication_required")
            if not initialized or final is None:
                raise ProviderError("Claude hat kein vollständiges Ergebnis bestätigt. Bitte den Ergebnisstatus prüfen.", "provider_result_missing", uncertain=True)
            if process.process.returncode != 0 or final.get("is_error") is not False or final.get("subtype") != "success":
                raise ProviderError("Claude konnte die Anfrage nicht abschließen. Anmeldung, Kontolimit und Modell prüfen.", "provider_execution_failed", uncertain=True)
            text = final.get("result")
            if not isinstance(text, str):
                text = "".join(assistant_text) or "".join(delta_text)
            result = finish_answer(text)
            result.update(provider_session_id=_identifier(final.get("session_id")) or session_id,
                          provider_turn_id=turn_id, usage=_usage(final.get("usage")))
            return result
    except (OSError, ValueError, TypeError) as error:
        raise ProviderError("Die lokale Claude-Verbindung wurde unterbrochen. Bitte den Ergebnisstatus prüfen.",
                            "provider_transport_failed", uncertain=submitted) from error
