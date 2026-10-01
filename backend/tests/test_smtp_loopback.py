"""Real loopback SMTP/TLS, spawn isolation, deadlines and worker cleanup.
IMMO_SMTP_FROZEN_PROBE selects a real PyInstaller build of DRIVER (--paths repo root).
Otherwise source/spawn only; GUI/service entrypoints need separate testing.
Loopback/.invalid data only; no SMTP mocks or OS certificate-store edits.
"""
import base64
import json
import os
import signal
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from ipaddress import ip_address
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
BODY, SUBJECT, PRIVATE = "Synthetic äöü body", "Synthetic subject", "PRIVATE-SMTP-ERROR"
DRIVER = r"""
import multiprocessing as mp
if __name__ == "__main__":
    mp.freeze_support()
import json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
def main():
    spec = json.loads(sys.stdin.readline())
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen: sys.path.insert(0, spec["root"])
    mp.set_start_method("spawn", force=True)
    from backend.services.integrations.providers import EmailIntegrationProvider
    stop, seen = threading.Event(), {}
    def observe():
        while not stop.wait(.002):
            for p in mp.active_children():
                try:
                    seen[p.pid] = getattr(p, "_start_method", None)
                except ValueError:
                    pass
    watcher = threading.Thread(target=observe)
    watcher.start()
    started = time.monotonic()
    try:
        def send(pair):
            return asdict(EmailIntegrationProvider().run(pair[1], pair[0]))
        with ThreadPoolExecutor(len(spec["configs"])) as pool:
            results = list(pool.map(send, zip(spec["configs"], spec["payloads"])))
    finally:
        elapsed = time.monotonic() - started
        stop.set(); watcher.join(1)
        children = mp.active_children()
        leaked = [p.pid for p in children]
        for p in children:
            p.kill(); p.join(2)
    print("RESULT=" + json.dumps(dict(results=results, elapsed=elapsed,
        workers=list(seen.values()), leaked=leaked, frozen=frozen)), flush=True)
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Whitelist diagnostics instead of echoing SMTP errors, addresses or
        # credentials. A failing child must still explain where it failed.
        import traceback
        code = "smtp_worker_cleanup_failed" if str(exc) == "smtp_worker_cleanup_failed" else "probe_failed"
        print("PROBE_ERROR=" + json.dumps(dict(error_type=type(exc).__name__, code=code,
            frames=[frame.name for frame in traceback.extract_tb(exc.__traceback__)])), flush=True)
        sys.exit(1)
"""

@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    root = tmp_path_factory.mktemp("smtp-ca")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "smtp.invalid")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.KeyUsage(True, False, True, False, False,
                                 True, True, None, None), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ip_address("127.0.0.1"))]), False).sign(key, hashes.SHA256()))
    ca, private_key = root / "test.pem", root / "test.key"
    ca.write_bytes(cert.public_bytes(ser.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8,
                ser.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, private_key)
    return ca, context

class SMTP(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, context, tag="a", fault="", barrier=None):
        self.context, self.fault, self.barrier = context, fault, barrier
        self.rows, self.errors, self.stop = [], [], threading.Event()
        super().__init__(("127.0.0.1", 0), Handler)
        self.config = dict(smtp_host="127.0.0.1", smtp_port=self.server_address[1],
            sender_email=f"from-{tag}@test.invalid", smtp_user=f"user-{tag}@test.invalid",
            smtp_password=f"synthetic-secret-{tag}", smtp_use_tls=True, smtp_use_ssl=False)
        self.payload = dict(recipient=f"to-{tag}@test.invalid", subject=SUBJECT,
                    body=f"<p>{BODY}:{tag}</p>", body_text=f"{BODY}:{tag}")
        self.thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": .05})
        self.thread.start()

    def close(self):
        self.stop.set()
        self.shutdown()
        for row in self.rows:
            try:
                row["socket"].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            row["socket"].close()
        self.server_close()
        self.thread.join(2)
        assert not self.thread.is_alive()

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        s, conn = self.server, self.request
        conn.settimeout(20)
        stream = conn.makefile("rb")
        row = dict(socket=conn, auth=None, sender=None, recipient=None, wire=b"",
                   accepted=False, tls=False, closed=threading.Event())
        s.rows.append(row)
        def reply(raw):
            conn.sendall(raw)
        def line():
            raw = stream.readline(65537)
            if not raw:
                raise EOFError
            return raw
        def command(verb):
            raw = line().decode("ascii").strip()
            if raw.split()[0].upper() != verb:
                raise ValueError("unexpected_smtp_command")
            return raw
        try:
            reply(b"220 smtp.invalid test-only\r\n")
            command("EHLO")
            reply(b"250-smtp.invalid\r\n250 STARTTLS\r\n")
            command("STARTTLS")
            reply(b"220 TLS ready\r\n")
            stream.close()
            conn = s.context.wrap_socket(conn, server_side=True, do_handshake_on_connect=False)
            row["socket"] = conn
            conn.do_handshake()
            stream, row["tls"] = conn.makefile("rb"), True
            command("EHLO")
            reply(b"250-smtp.invalid\r\n250 AUTH PLAIN\r\n")
            parts = command("AUTH").split()
            if len(parts) != 3 or parts[1] != "PLAIN":
                raise ValueError("expected_auth_plain")
            _, user, password = base64.b64decode(parts[2], validate=True).decode().split("\0")
            row["auth"] = (user, password)
            if s.barrier:
                s.barrier.wait(8)
            if s.fault == "auth" or row["auth"] != (s.config["smtp_user"], s.config["smtp_password"]):
                reply(f"535 {PRIVATE} {s.config['smtp_password']}\r\n".encode())
                return
            reply(b"235 Authenticated\r\n")
            row["sender"] = command("MAIL").split("<", 1)[1].split(">", 1)[0]
            reply(b"250 Sender OK\r\n")
            row["recipient"] = command("RCPT").split("<", 1)[1].split(">", 1)[0]
            if s.fault == "rcpt":
                reply(f"550 {PRIVATE} {s.payload['recipient']}\r\n".encode())
                command("RSET")
                reply(b"250 Reset\r\n")
                return
            reply(b"250 Recipient OK\r\n")
            command("DATA")
            reply(b"354 End with dot\r\n")
            while (raw := line()) != b".\r\n":
                row["wire"] += raw[1:] if raw.startswith(b"..") else raw
            row["data_complete"] = True
            if s.fault == "hang":
                while not s.stop.is_set() and conn.recv(1):
                    pass
                return
            if s.fault == "drip":
                reply(b"250 ")
                while not s.stop.wait(.05):
                    reply(b"x")
                return
            reply(b"250 Accepted into test memory\r\n")
            row["accepted"] = True
            command("QUIT")
            reply(b"221 Bye\r\n")
        except (EOFError, OSError):
            pass
        except Exception as exc:
            s.errors.append(type(exc).__name__)
        finally:
            stream.close()
            conn.close()
            row["closed"].set()

@pytest.fixture
def servers(tls):
    instances = []
    def create(**options):
        server = SMTP(tls[1], **options)
        instances.append(server)
        return server
    yield create
    for server in instances:
        server.close()

@pytest.fixture(scope="module")
def runner(tmp_path_factory, tls):
    frozen = bool(os.environ.get("IMMO_SMTP_FROZEN_PROBE"))
    root = tmp_path_factory.mktemp("smtp-probe")
    script = root / "smtp_probe.py"
    script.write_text(DRIVER, encoding="utf-8")
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
           if k in os.environ}
    env.update({k: str(root) for k in ("HOME", "TEMP", "TMP", "TMPDIR", "APPDATA", "LOCALAPPDATA", "DATA_DIR")})
    env.update(PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1", SSL_CERT_FILE=str(tls[0]), SSL_CERT_DIR=str(root),
        DATABASE_URL="sqlite:///:memory:", INTEGRATION_STATE_FILE="", ENVIRONMENT="development",
        SQLITE_PERSISTENT_STORE="false", ALLOW_INMEMORY_FALLBACK="true", AI_ENABLED="false",
        AUTO_MIGRATE="false", AUTO_SEED_DEMO_DATA="false", JWT_SECRET_KEY="synthetic.invalid")
    command = [sys.executable, str(script)]
    if frozen:
        executable = Path(os.environ["IMMO_SMTP_FROZEN_PROBE"]).resolve()
        assert executable.is_file()
        command = [str(executable)]
    return command, root, env, frozen

def run_probe(runner, servers, *, empty=False, seconds=12):
    command, root, env, frozen = runner
    spec = dict(root=str(ROOT),
        configs=[{} if empty else {**s.config, "smtp_timeout_seconds": seconds} for s in servers],
        payloads=[s.payload for s in servers])
    proc = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        start_new_session=os.name != "nt")
    try:
        out, err = proc.communicate(json.dumps(spec) + "\n", timeout=30)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        finally:
            proc.kill()
            proc.communicate(timeout=5)
        pytest.fail("Safety deadline exceeded")
    forbidden = [PRIVATE, BODY, SUBJECT] + [
        v for s in servers for v in (s.config["smtp_user"], s.config["smtp_password"],
                            s.config["sender_email"], s.payload["recipient"])]
    assert not any(v in out + err for v in forbidden), "SMTP data leaked"
    diagnostics = [line[12:] for line in out.splitlines() if line.startswith("PROBE_ERROR=")]
    assert proc.returncode == 0, f"Probe failed: {diagnostics or ['no safe diagnostic']}; stderr withheld"
    lines = [line[7:] for line in out.splitlines() if line.startswith("RESULT=")]
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert report["frozen"] is frozen and report["leaked"] == []
    if not empty:
        assert len(report["workers"]) >= len(servers)
        assert set(report["workers"]) == {"spawn"}
    for server in servers:
        for row in server.rows:
            assert row["closed"].wait(2)
        assert not server.errors, server.errors
    return report

def test_unconfigured(runner, servers):
    s = servers()
    r = run_probe(runner, [s], empty=True)
    assert not r["workers"] and not s.rows
    a = r["results"][0]
    assert a["success"] is False and a["details"]["status"] == "not_sent"

def test_acceptance_and_parallel_configs(runner, servers):
    gate = threading.Barrier(2)
    pair = [servers(tag=t, barrier=gate) for t in ("alpha", "beta")]
    r = run_probe(runner, pair)
    assert len(r["results"]) == 2
    for a, s in zip(r["results"], pair):
        assert a["success"] and a["details"]["status"] == "accepted"
        assert a["details"]["delivery_confirmed"] is False
        assert len(s.rows) == 1
        row = s.rows[0]
        assert row["tls"] and row["accepted"]
        assert row["auth"] == (s.config["smtp_user"], s.config["smtp_password"])
        assert (row["sender"], row["recipient"]) == (
            s.config["sender_email"], s.payload["recipient"])
        msg = BytesParser(policy=policy.default).parsebytes(row["wire"])
        assert s.payload["body_text"] in msg.get_body(preferencelist=("plain",)).get_content()

@pytest.mark.parametrize("fault", ["auth", "rcpt"])
def test_rejections(runner, servers, fault):
    s = servers(fault=fault)
    a = run_probe(runner, [s])["results"][0]
    assert not a["success"] and a["details"]["status"] == "not_sent"
    assert len(s.rows) == 1
    row = s.rows[0]
    assert row["tls"] and not row["wire"] and not row["accepted"]
    assert row["auth"] == (s.config["smtp_user"], s.config["smtp_password"])
    if fault == "auth":
        assert row["sender"] is None

@pytest.mark.parametrize("fault", ["hang", "drip"])
def test_global_deadline_and_cleanup(runner, servers, fault):
    s = servers(fault=fault)
    r = run_probe(runner, [s], seconds=4)
    a = r["results"][0]
    assert not a["success"] and a["details"]["status"] == "unknown"
    assert a["details"]["code"] == "deadline_exceeded"
    assert a["details"]["retry_automatically"] is False
    assert 3.8 <= r["elapsed"] <= 5.5  # Includes spawn, TLS, SMTP and cleanup.
    time.sleep(.2)
    assert len(s.rows) == 1
    assert s.rows[0].get("data_complete")
    assert not s.rows[0]["accepted"]
