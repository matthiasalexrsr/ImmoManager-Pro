"""Claude CLI contract repros use synthetic child processes; no provider calls."""

import base64
import json
import queue
import sys
from collections import deque
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.services import assistant_provider_claude as claude
from backend.services.assistant_provider_process import CliProcess, private_environment
from backend.services.assistant_provider_protocol import ProviderError
from backend.services.assistant_provider_vault import ProfileLease


def frame(**event):
    return ("stdout", json.dumps(event) + "\n")


def init(**extra):
    return frame(type="system", subtype="init", tools=[], mcp_servers=[], plugins=[], session_id="session-synthetic", **extra)


def final(text="Antwort", **extra):
    return frame(type="result", subtype="success", is_error=False, result=text,
                 session_id="session-synthetic", **extra)


class Child:
    def __init__(self, argv, path, script):
        self.argv, self.path = argv, path
        self.pending = deque(script.get("events", []))
        if not script.get("hang"):
            self.pending.extend([("stdout_closed", ""), ("stderr_closed", "")])
        self.returncode = script.get("returncode", 0)
        self.hang = script.get("hang", False)
        self.writes = []
        self.closed = self.input_closed = False
        self.process = self

    def poll(self):
        return None if self.pending or self.hang else self.returncode

    def next_line(self, timeout=.2):
        return self.pending.popleft() if self.pending else None

    def write_line(self, text):
        self.writes.append(text)

    def close_stdin(self):
        self.input_closed = True

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@pytest.fixture
def transport(monkeypatch, tmp_path):
    scripts: deque[dict[str, Any]] = deque()
    children = []

    def create(argv, profile, **kwargs):
        child = Child(argv, profile, scripts.popleft())
        children.append(child)
        return child

    monkeypatch.setattr(claude, "CliProcess", create)
    return SimpleNamespace(scripts=scripts, children=children,
                           profile=SimpleNamespace(provider="claude", path=tmp_path), executable=["synthetic-claude"])


def execute(transport, request=None, emit=None, cancelled=None):
    return claude.execute(transport.profile, transport.executable, request or {}, emit or (lambda event: None),
                          cancelled or (lambda: False))


@pytest.mark.parametrize("url", [
    "http://claude.ai/oauth/authorize", "https://claude.ai.evil.test/oauth/authorize",
    "https://evil.test/https://claude.ai/oauth/authorize", "https://claude.ai@evil.test/oauth/authorize",
    "https://user:password@claude.ai/oauth/authorize", "https://claude.ai:9999/oauth/authorize",
    "https://claude.ai/oauth/authorize?access_token=HIDDEN", "https://claude.ai/oauth/authorize#HIDDEN",
    "https://claude.ai/help", "https://console.anthropic.com/login?api_key=HIDDEN",
])
def test_only_trusted_public_authorization_urls_are_accepted(url):
    assert claude._auth_url(url) is None


def test_login_forwards_one_time_code_only_to_stdin_and_rechecks_auth(transport):
    secret = "SYNTHETIC-ONETIME-CODE#SYNTHETIC-STATE"
    transport.scripts.extend([
        {"events": [("stderr", "No browser: https://claude.ai/oauth/authorize?code=true&state=synthetic\n"),
                    ("stdout", "Code echoed by test child: " + secret + "\n")]},
        {"events": [frame(loggedIn=True, authMethod="claude.ai", apiProvider="firstParty",
                          subscriptionType="pro", accessToken="DO-NOT-PUBLISH", configDirectory="PRIVATE-PATH")]},
    ])
    codes: queue.Queue[str] = queue.Queue()
    public: list[dict] = []
    codes.put(secret)
    result = claude.login(transport.profile, transport.executable, public.append, lambda: False, codes)
    assert result == {"connected": True, "auth_method": "claude.ai", "subscription_type": "pro"}
    assert transport.children[0].argv == ["synthetic-claude", "auth", "login", "--claudeai"]
    assert transport.children[1].argv == ["synthetic-claude", "auth", "status", "--json"]
    assert transport.children[0].writes == [secret]
    assert public[0]["can_submit_code"] is True and public[1]["can_submit_code"] is False
    assert secret not in str(public) + str(result)
    assert "DO-NOT-PUBLISH" not in str(public) + str(result)
    assert "PRIVATE-PATH" not in str(result)
    assert all(child.closed for child in transport.children)


@pytest.mark.parametrize("status", [
    {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"},
    {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"},
    {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"},
])
def test_wrong_auth_type_is_never_connected(transport, status):
    transport.scripts.append({"events": [frame(**status)]})
    assert claude.status(transport.profile, transport.executable, lambda: False) == {"connected": False, "auth_method": "none"}


def test_failed_login_and_stderr_are_safely_reported(transport):
    transport.scripts.append({"events": [("stderr", "PRIVATE-TOKEN=never-public\n")], "returncode": 1})
    with pytest.raises(ProviderError) as error:
        claude.login(transport.profile, transport.executable, lambda event: pytest.fail("No public state"), lambda: False, queue.Queue())
    assert error.value.code == "authentication_failed"
    assert "PRIVATE-TOKEN" not in str(error.value)
    assert transport.children[0].closed


def test_login_code_cannot_inject_another_stdin_command(transport):
    transport.scripts.append({"events": [("stdout", "https://claude.ai/oauth/authorize?code=true\n")]})
    codes: queue.Queue[str] = queue.Queue()
    codes.put("code\n/command")
    with pytest.raises(ProviderError) as error:
        claude.login(transport.profile, transport.executable, lambda event: None, lambda: False, codes)
    assert error.value.code == "invalid_authentication_code"
    assert transport.children[0].writes == [] and transport.children[0].closed


def test_duplicate_one_time_code_is_not_forwarded_twice(transport):
    transport.scripts.extend([
        {"events": [("stdout", "https://claude.ai/oauth/authorize?code=true\n"), ("stdout", "Checking\n"), ("stdout", "Done\n")]},
        {"events": [frame(loggedIn=True, authMethod="claude.ai", apiProvider="firstParty")]},
    ])
    codes: queue.Queue[str] = queue.Queue()
    codes.put("synthetic-code")
    codes.put("synthetic-code")
    claude.login(transport.profile, transport.executable, lambda event: None, lambda: False, codes)
    assert transport.children[0].writes == ["synthetic-code"]


def test_execute_argv_input_inline_image_and_streamed_final_answer(transport):
    transport.scripts.append({"events": [init(), frame(type="stream_event", event={"type": "message_start", "message": {"id": "msg-synthetic"}}),
        frame(type="stream_event", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Antwort"}}),
        frame(type="assistant", message={"id": "msg-synthetic", "content": [{"type": "text", "text": "Antwort"}]}),
        final("Antwort", usage={"input_tokens": 20, "output_tokens": 3, "private": "NEVER-PUBLISH", "cache_read_input_tokens": True})]})
    image = base64.b64encode(b"synthetic-image").decode()
    request = {"model": "claude-sonnet-test", "effort": "high", "messages": [{"role": "user", "content": "Prüfe nur diese Auswahl"}],
               "context": {"sources": []}, "attachments": [{"id": "selected", "name": "Foto.png", "mime": "image/png", "text": None, "data_base64": image}],
               "unselected_secret": "DO-NOT-SEND", "provider_session_id": "DO-NOT-RESUME"}
    events: list[dict] = []
    result = execute(transport, request, events.append)
    child = transport.children[0]
    assert all(flag in child.argv for flag in ["--restricted", "--safe-mode", "--strict-mcp-config", "--no-chrome",
                                                "--no-session-persistence", "--disable-slash-commands", "--include-partial-messages"])
    for flag, value in [("--tools", ""), ("--mcp-config", '{"mcpServers":{}}'), ("--setting-sources", ""),
                        ("--permission-mode", "dontAsk"), ("--permission-prompts", "none"),
                        ("--input-format", "stream-json"), ("--output-format", "stream-json")]:
        assert child.argv[child.argv.index(flag) + 1] == value
    assert "--resume" not in child.argv and "--continue" not in child.argv and "--bare" not in child.argv
    assert "DO-NOT-SEND" not in str(child.writes) and "DO-NOT-RESUME" not in str(child.writes)
    payload = json.loads(child.writes[0])
    assert payload["message"]["content"][1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}}
    assert image not in payload["message"]["content"][0]["text"]
    assert events == [{"type": "delta", "text": "Antwort"}]
    assert result == {"text": "Antwort", "proposals": [], "provider_session_id": "session-synthetic", "provider_turn_id": "msg-synthetic",
                      "usage": {"input_tokens": 20, "output_tokens": 3}}
    assert child.input_closed and child.closed


def test_explicit_web_research_enables_only_websearch(transport):
    transport.scripts.append({"events": [frame(type="system", subtype="init", tools=["WebSearch"], mcp_servers=[], plugins=[]), final()]})
    execute(transport, {"web_research": True})
    argv = transport.children[0].argv
    assert argv[argv.index("--tools") + 1] == "WebSearch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch"


@pytest.mark.parametrize("loaded", [{"tools": ["Bash"]}, {"tools": ["Read"]}, {"mcp_servers": [{"name": "unapproved"}]}, {"plugins": ["unexpected"]}])
def test_unexpected_tools_mcp_or_plugins_abort_and_close_process(transport, loaded):
    event = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "plugins": [], **loaded}
    transport.scripts.append({"events": [frame(**event), final()]})
    with pytest.raises(ProviderError) as error:
        execute(transport)
    assert error.value.code == "provider_isolation_failed" and error.value.uncertain
    assert transport.children[0].closed


@pytest.mark.parametrize("events,returncode,code", [
    ([init(), ("stderr", "SECRET=hidden\n")], 1, "provider_result_missing"),
    ([init(), frame(type="result", subtype="error_during_execution", is_error=True, result="SECRET=hidden")], 1, "provider_execution_failed"),
    ([init(), ("stdout", "SECRET=hidden\n")], 0, "provider_protocol_error"),
    ([final()], 0, "provider_result_missing"),
    ([init(), final()], 1, "provider_execution_failed"),
])
def test_incomplete_error_and_nonjson_output_never_leak_raw_diagnostics(transport, events, returncode, code):
    transport.scripts.append({"events": events, "returncode": returncode})
    with pytest.raises(ProviderError) as error:
        execute(transport)
    assert error.value.code == code and error.value.uncertain
    assert "SECRET" not in str(error.value)
    assert transport.children[0].closed


def test_cancellation_after_submission_is_uncertain_and_closes_only_owned_child(transport):
    transport.scripts.append({"events": [init()], "hang": True})
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 3

    with pytest.raises(ProviderError) as error:
        execute(transport, cancelled=cancelled)
    assert error.value.code == "cancelled" and error.value.uncertain
    assert transport.children[0].closed


def test_cancellation_before_submission_never_starts_a_process(transport):
    with pytest.raises(ProviderError) as error:
        execute(transport, cancelled=lambda: True)
    assert error.value.code == "cancelled" and not error.value.uncertain
    assert not transport.children


def test_timeout_closes_owned_child_and_does_not_claim_no_provider_usage(transport, monkeypatch):
    transport.scripts.append({"events": [init()], "hang": True})
    clock = iter([0, 1000])
    monkeypatch.setattr(claude.time, "monotonic", lambda: next(clock))
    with pytest.raises(ProviderError) as error:
        execute(transport)
    assert error.value.code == "provider_timeout" and error.value.uncertain
    assert transport.children[0].closed


def test_proposal_block_is_extracted_but_never_applied(transport):
    proposal = {"kind": "task", "values": {"title": "Prüfen"}, "anchor": {"kind": "property", "id": "synthetic"}, "evidence": []}
    text = "Bitte prüfen.\n```immomanager-proposals\n" + json.dumps([proposal]) + "\n```"
    transport.scripts.append({"events": [init(), final(text)]})
    result = execute(transport)
    assert result["text"] == "Bitte prüfen." and result["proposals"] == [proposal]


@pytest.mark.parametrize("error_details", [
    {"errors": ["Not logged in · Please run /login"]},
    {"error": {"type": "authentication_error", "message": "PRIVATE-TOKEN"}},
    {"error": "oauth_org_not_allowed"},
    {"result": "OAuth token has expired: PRIVATE-TOKEN"},
])
def test_terminal_authentication_failure_requires_reconnect_without_exposing_diagnostics(transport, error_details):
    # An auth failure may happen before the normal system/init event as well.
    transport.scripts.append({"events": [frame(type="result", subtype="error_during_execution", is_error=True, **error_details)], "returncode": 1})
    with pytest.raises(ProviderError) as error:
        execute(transport)
    assert error.value.code == "authentication_required" and not error.value.uncertain
    assert "PRIVATE-TOKEN" not in str(error.value)
    assert transport.children[0].closed


def test_successful_answer_about_login_and_retry_notice_do_not_disconnect_account(transport):
    transport.scripts.append({"events": [init(), frame(type="system", subtype="api_retry", error="authentication_failed"),
                                         final("The document says not logged in; please run /login.")]})
    assert execute(transport)["text"] == "The document says not logged in; please run /login."


def test_private_environment_cannot_inherit_provider_keys_or_operator_profile(transport, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "DO-NOT-INHERIT")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "DO-NOT-INHERIT")
    monkeypatch.setenv("OPENAI_API_KEY", "DO-NOT-INHERIT")
    monkeypatch.setenv("SECRET_KEY", "DO-NOT-INHERIT")
    env = private_environment(transport.profile.path)
    assert not any("DO-NOT-INHERIT" in value for value in env.values())
    assert env["CLAUDE_CONFIG_DIR"] == env["HOME"] == env["USERPROFILE"] == str(transport.profile.path)


@pytest.mark.parametrize("payload", [{"effort": "invalid"}, {"model": "--dangerously-skip-permissions"},
                                      {"attachments": [{"mime": "image/png", "data_base64": "not valid"}]},
                                      {"attachments": [{"mime": "text/html", "data_base64": "eA=="}]}])
def test_invalid_model_effort_or_image_is_rejected_before_submitting(transport, payload):
    with pytest.raises(ProviderError) as error:
        execute(transport, payload)
    assert not error.value.uncertain and not transport.children


def test_real_owned_stdio_process_receives_one_frame_and_cleanly_exits(tmp_path, monkeypatch):
    """Python is the synthetic executable; the actual shared process owner runs."""
    script = tmp_path / "child.py"
    script.write_text(
        "import json,sys\n"
        "from pathlib import Path\n"
        "data=json.loads(sys.stdin.read())\n"
        "Path('captured.json').write_text(json.dumps(data), encoding='utf-8')\n"
        "print(json.dumps({'type':'system','subtype':'init','tools':[],'mcp_servers':[],'plugins':[]}))\n"
        "print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':'Synthetic owned process'}))\n",
        encoding="utf-8")
    monkeypatch.setattr(claude, "CliProcess", CliProcess)
    profile = cast(ProfileLease, SimpleNamespace(provider="claude", path=tmp_path))
    result = claude.execute(profile, [sys.executable, str(script)], {"messages": [{"role": "user", "content": "Only selected text"}]},
                            lambda event: None, lambda: False)
    assert result["text"] == "Synthetic owned process"
    captured = json.loads((tmp_path / "work" / "captured.json").read_text(encoding="utf-8"))
    assert captured["type"] == "user" and "Only selected text" in captured["message"]["content"][0]["text"]


def test_real_owned_process_is_reaped_after_cancel(tmp_path, monkeypatch):
    script = tmp_path / "waiting-child.py"
    script.write_text("import sys,time\nfrom pathlib import Path\nsys.stdin.read()\nPath('ready').write_text('ready')\ntime.sleep(30)\n", encoding="utf-8")
    children = []

    def create(argv, profile, **kwargs):
        child = CliProcess(argv, profile, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(claude, "CliProcess", create)
    monkeypatch.setattr(claude, "EXECUTE_TIMEOUT", 5)
    profile = cast(ProfileLease, SimpleNamespace(provider="claude", path=tmp_path))
    with pytest.raises(ProviderError) as error:
        claude.execute(profile, [sys.executable, str(script)], {}, lambda event: None,
                       lambda: (tmp_path / "work" / "ready").exists())
    assert error.value.code == "cancelled" and error.value.uncertain
    assert len(children) == 1 and children[0].process.poll() is not None
