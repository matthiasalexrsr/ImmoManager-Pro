"""Independent account/protocol review repros; no real login or inference."""

import json
import os
import queue
import subprocess
import sys
import time
from collections import deque
from types import SimpleNamespace
from typing import cast

import pytest

from backend.services import assistant_provider_codex as codex
from backend.services import assistant_provider_process as owned_process
from backend.services import assistant_provider_prompt as prompt
from backend.services import assistant_provider_vault as vault
from backend.services import assistant_providers as hub
from backend.services.assistant_provider_protocol import ProviderError
from backend.services.secret_box import SecretBox, write_private_file


@pytest.fixture
def private_vault(monkeypatch, tmp_path):
    data, uploads = tmp_path / "data", tmp_path / "uploads"
    data.mkdir()
    uploads.mkdir()
    box = SecretBox(tmp_path / "keys.json")
    monkeypatch.setattr(vault, "get_data_dir", lambda: data)
    monkeypatch.setattr(vault, "get_uploads_dir", lambda: uploads)
    monkeypatch.setattr(vault, "default_secret_box", lambda: box)
    monkeypatch.setattr(hub, "get_data_dir", lambda: data)
    return SimpleNamespace(data=data, uploads=uploads)


def save_account(actor="actor-a", *, connected=True):
    with vault.ProfileLease(actor, "codex") as lease:
        assert lease.path is not None
        write_private_file(lease.path / "auth.json", b'{"token":"synthetic-private-token"}')
        lease.save({"connected": connected, "auth_mode": "chatgpt"})
    return vault._vault_path(actor, "codex")


def test_account_vault_is_encrypted_actor_bound_and_plaintext_lease_is_removed(private_vault):
    path = save_account()
    assert "synthetic-private-token" not in path.read_text(encoding="utf-8")
    with vault.ProfileLease("actor-a", "codex") as lease:
        assert lease.path is not None
        directory = lease.path
        assert (directory / "auth.json").read_bytes() == b'{"token":"synthetic-private-token"}'
    assert not directory.exists()
    other = vault._vault_path("actor-b", "codex")
    other.parent.mkdir(parents=True)
    other.write_bytes(path.read_bytes())
    with pytest.raises(ProviderError) as rejected:
        vault.load("actor-b", "codex")
    assert rejected.value.code == "credentials_unavailable"


def test_corrupted_vault_can_be_explicitly_disconnected(private_vault):
    path = save_account()
    path.write_bytes(b"corrupted encrypted envelope")
    vault.disconnect("actor-a", "codex")
    assert not path.exists()


def test_failed_execution_does_not_promote_disconnected_credentials_to_connected(private_vault, monkeypatch):
    save_account(connected=False)

    def failed(*args, **kwargs):
        raise ProviderError("Synthetic cancelled request", "cancelled", uncertain=True)

    monkeypatch.setattr(hub, "executable", lambda provider: ["synthetic-codex"])
    monkeypatch.setattr(hub, "_adapter", lambda provider: SimpleNamespace(execute=failed))
    with pytest.raises(ProviderError):
        hub.execute("actor-a", "codex", {}, lambda event: None, lambda: False)
    assert vault.load("actor-a", "codex")["public"]["connected"] is False


def test_failed_login_does_not_replace_existing_credentials(private_vault, monkeypatch):
    path = save_account()
    before = path.read_bytes()

    def failed(profile, *args, **kwargs):
        write_private_file(profile.path / "auth.json", b'{"token":"failed-partial-login"}')
        raise ProviderError("Synthetic failed login", "authentication_required")

    monkeypatch.setattr(hub, "executable", lambda provider: ["synthetic-codex"])
    monkeypatch.setattr(hub, "_adapter", lambda provider: SimpleNamespace(login=failed))
    hub.start_login("actor-a", "codex")
    job = hub._logins[hub._identity("actor-a", "codex")]
    job["thread"].join(timeout=5)
    assert not job["thread"].is_alive()
    assert job["public"]["status"] == "failed"
    assert path.read_bytes() == before
    assert not list((private_vault.data / "assistant-runtime").glob("*-codex-*"))


class ScenarioRpc:
    def __init__(self, *, events=(), verification_url="https://auth.openai.com/codex/device", cancel_error=False):
        self.calls = []
        self.events = deque(events)
        self.verification_url, self.cancel_error = verification_url, cancel_error
        self.closed = False

    def call(self, method, params=None, **kwargs):
        self.calls.append((method, params))
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method == "thread/start":
            return {"thread": {"id": "thread-current"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-current"}}
        if method == "account/login/start":
            return {"type": "chatgptDeviceCode", "loginId": "login-current", "verificationUrl": self.verification_url, "userCode": "SYNTHETIC"}
        if method == "account/login/cancel" and self.cancel_error:
            raise ProviderError("Synthetic interruption of cancel", "provider_timeout")
        return {}

    def event(self):
        return self.events.popleft() if self.events else None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


def test_codex_already_cancelled_request_never_starts_a_model_turn(monkeypatch, tmp_path):
    rpc = ScenarioRpc()
    monkeypatch.setattr(codex, "CodexRpc", lambda *a, **k: rpc)
    with pytest.raises(ProviderError) as cancelled:
        codex.execute(SimpleNamespace(path=tmp_path), ["synthetic"], {}, lambda event: None, lambda: True)
    assert cancelled.value.code == "cancelled"
    assert not any(method == "turn/start" for method, _ in rpc.calls)


def test_login_cancel_rpc_failure_still_reports_cancelled(monkeypatch):
    rpc = ScenarioRpc(cancel_error=True)
    monkeypatch.setattr(codex, "CodexRpc", lambda *a, **k: rpc)
    states = iter([False, True])
    with pytest.raises(ProviderError) as cancelled:
        codex.login(SimpleNamespace(), ["synthetic"], lambda event: None, lambda: next(states), queue.Queue())
    assert cancelled.value.code == "cancelled"
    assert any(method == "account/login/cancel" for method, _ in rpc.calls)


@pytest.mark.parametrize("url", ["https://user:PRIVATE-PASSWORD@auth.openai.com/codex/device", "https://auth.openai.com:7777/codex/device"])
def test_codex_login_rejects_userinfo_and_non_https_service_port(monkeypatch, url):
    rpc = ScenarioRpc(verification_url=url)
    monkeypatch.setattr(codex, "CodexRpc", lambda *a, **k: rpc)
    emitted: list[dict] = []
    states = iter([False, True])
    with pytest.raises(ProviderError) as rejected:
        codex.login(SimpleNamespace(), ["synthetic"], emitted.append, lambda: next(states), queue.Queue())
    assert rejected.value.code == "protocol_incompatible" and not emitted


def test_codex_drops_other_turn_items_even_on_same_thread(monkeypatch, tmp_path):
    events = [
        {"method": "item/completed", "params": {"threadId": "thread-current", "turnId": "turn-other",
            "item": {"id": "foreign", "type": "agentMessage", "phase": "final_answer", "text": "UNRELATED-CONTENT"}}},
        {"method": "item/completed", "params": {"threadId": "thread-current", "turnId": "turn-current",
            "item": {"id": "own", "type": "agentMessage", "phase": "final_answer", "text": "Current answer"}}},
        {"method": "turn/completed", "params": {"threadId": "thread-current", "turn": {"id": "turn-current", "status": "completed"}}},
    ]
    rpc = ScenarioRpc(events=events)
    monkeypatch.setattr(codex, "CodexRpc", lambda *a, **k: rpc)
    result = codex.execute(SimpleNamespace(path=tmp_path), ["synthetic"], {}, lambda event: None, lambda: False)
    assert result["text"] == "Current answer"


@pytest.mark.parametrize("payload", [None, [], 2, {"id": [1], "result": {}}])
def test_invalid_rpc_frames_become_safe_protocol_error(payload):
    rpc = object.__new__(codex.CodexRpc)
    rpc.transport = cast(owned_process.CliProcess, SimpleNamespace(next_line=lambda timeout: ("stdout", json.dumps(payload)), write_line=lambda line: None))
    rpc.responses, rpc.events = {}, deque()
    with pytest.raises(ProviderError) as rejected:
        rpc._read()
    assert rejected.value.code == "protocol_incompatible"


def test_crash_cleanup_stays_with_exact_actor_and_provider(private_vault):
    root = private_vault.data / "assistant-runtime"
    root.mkdir()
    stale = root / (vault.actor_key("actor-a") + "-codex-stale")
    foreign = root / (vault.actor_key("actor-b") + "-codex-stale")
    other_provider = root / (vault.actor_key("actor-a") + "-claude-stale")
    for directory in (stale, foreign, other_provider):
        directory.mkdir()
        (directory / "sentinel").write_text("synthetic private data", encoding="utf-8")
    with vault.ProfileLease("actor-a", "codex", restore=False):
        assert not stale.exists()
        assert (foreign / "sentinel").exists() and (other_provider / "sentinel").exists()


def test_close_never_follows_profile_link_into_another_account(private_vault):
    root = private_vault.data / "assistant-runtime"
    root.mkdir()
    foreign = root / (vault.actor_key("actor-b") + "-codex-active")
    foreign.mkdir()
    sentinel = foreign / "sentinel"
    sentinel.write_text("foreign synthetic data", encoding="utf-8")
    alias = root / (vault.actor_key("actor-a") + "-codex-link")
    try:
        alias.symlink_to(foreign, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit an unprivileged directory symlink")
    lease = object.__new__(vault.ProfileLease)
    lease.actor_id, lease.provider = "actor-a", "codex"
    lease.root, lease.path, lease.handle, lease.lock = root, alias, None, None
    lease.close()
    assert sentinel.exists(), "Cleanup followed a profile link into another actor's private directory"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job ownership regression")
def test_owned_job_reaps_child_and_grandchild_and_leaves_unrelated_process(tmp_path):
    import ctypes
    from ctypes import wintypes

    child = tmp_path / "spawn-child.py"
    child.write_text("import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=getattr(subprocess, 'CREATE_NO_WINDOW'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nprint(p.pid,flush=True)\ntime.sleep(30)\n", encoding="utf-8")
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW'), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    kernel = getattr(ctypes, 'WinDLL')("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    grandchild_handle = None
    try:
        with owned_process.CliProcess([sys.executable, str(child)], tmp_path) as process:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                line = process.next_line()
                if line and line[0] == "stdout":
                    grandchild_handle = kernel.OpenProcess(0x00100000, False, int(line[1].strip()))  # SYNCHRONIZE
                    assert grandchild_handle
                    break
            assert grandchild_handle, "Synthetic grandchild did not start"
        assert process.process.poll() is not None
        assert kernel.WaitForSingleObject(grandchild_handle, 3000) == 0
        assert unrelated.poll() is None
    finally:
        if grandchild_handle:
            kernel.CloseHandle(grandchild_handle)
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_stdin_write_to_nonreading_child_has_timeout_and_reaps_it(tmp_path):
    started = time.monotonic()
    with owned_process.CliProcess([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path) as process:
        with pytest.raises(ProviderError) as blocked:
            process.write_line("synthetic-text-" * 50_000, timeout=.1)
        assert blocked.value.code == "provider_timeout" and blocked.value.uncertain
        assert process.process.poll() is not None
    assert time.monotonic() - started < 5


def test_successful_login_is_not_invalidated_by_optional_model_discovery(monkeypatch):
    rpc = ScenarioRpc(events=[{"method": "account/login/completed", "params": {"loginId": "login-current", "success": True}}])
    original = rpc.call

    def call(method, params=None, **kwargs):
        if method == "model/list":
            raise ProviderError("Synthetic transient discovery error", "provider_timeout")
        return original(method, params, **kwargs)

    monkeypatch.setattr(rpc, "call", call)
    monkeypatch.setattr(codex, "CodexRpc", lambda *a, **k: rpc)
    result = codex.login(SimpleNamespace(), ["synthetic"], lambda event: None, lambda: False, queue.Queue())
    assert result["connected"] is True and result["auth_mode"] == "chatgpt"


def test_deeply_nested_model_proposal_does_not_discard_readable_answer():
    depth = sys.getrecursionlimit() + 100
    text = "Readable answer.\n```immomanager-proposals\n" + "[" * depth + "{}" + "]" * depth + "\n```"
    result = prompt.finish_answer(text)
    assert "Readable answer." in result["text"] and result["proposals"] == []
    assert "vorschlag" in result["text"].lower()
