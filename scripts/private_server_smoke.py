"""Disposable Docker/PostgreSQL acceptance; never use an existing installation.

Only generated immo-private-ci-* projects are created and removed. Tests use
synthetic accounts/files; no remote VPN endpoint or message delivery is invoked.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.configure_private_server import configure  # noqa: E402
from scripts.private_server_backup import BackupError, backup, restore  # noqa: E402

PASSWORD = "synthetic private test passphrase"
FILE_BYTES = b"Private server acceptance file; synthetic data only.\n"


def totp(secret: str) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000:06d}"


class Installation:
    def __init__(self, project: str, environment: Path, port: int):
        assert project.startswith("immo-private-ci-") and len(project) < 64
        self.project, self.environment = project, environment
        self.base = f"http://127.0.0.1:{port}"
        self.env = dict(os.environ)
        # Dotenv values, not unrelated process values, define this installation.
        for key in ("APP_HOST", "APP_ORIGIN", "APP_HTTP_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "JWT_SECRET_KEY", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_ENV_FILES", "COMPOSE_PROFILES"):
            self.env.pop(key, None)

    def compose(self, *arguments: str, input: bytes | None = None, expected: int = 0, timeout: int = 900):
        command = ["docker", "compose", "--project-name", self.project, "--env-file", str(self.environment),
                   "-f", str(ROOT / "compose.private-server.yml"), *arguments]
        result = subprocess.run(command, input=input, cwd=ROOT, env=self.env, capture_output=True, timeout=timeout)
        if result.returncode != expected:
            output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
            values = dict(line.split('=', 1) for line in self.environment.read_text().splitlines() if '=' in line)
            for secret in (values.get('POSTGRES_PASSWORD'), values.get('JWT_SECRET_KEY'), PASSWORD):
                if secret:
                    output = output.replace(secret, '[redacted]')
            raise RuntimeError(f"Disposable Compose operation {arguments[0]} failed (exit {result.returncode}):\n{output[-8000:]}")
        return result

    def request(self, path: str, *, method="GET", data=None, token=None, expected=200, raw=None, headers=None):
        request_headers = dict(headers or {})
        if token:
            request_headers["Authorization"] = "Bearer " + token
        if data is not None:
            raw = json.dumps(data).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=raw, method=method, headers=request_headers)
        try:
            with urlopen(request, timeout=20) as response:
                status, body = response.status, response.read(4 * 1024 * 1024)
        except HTTPError as error:
            status, body = error.code, error.read(1024 * 1024)
        assert status == expected, f"{method} {path}: expected {expected}, got {status}"
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            return body

    def login(self, username="ci_owner", secret=None):
        result = self.request("/api/v1/auth/login", method="POST", data={
            "username": username, "password": PASSWORD, **({"totp_code": totp(secret)} if secret else {})})
        return result["access_token"]


def seed(installation: Installation, owner: str) -> dict:
    def create(path, payload):
        return installation.request("/api/v1" + path, method="POST", token=owner, data=payload, expected=201)
    viewers = [create("/auth/users", {"username": f"viewer{index}", "email": f"viewer{index}@example.invalid",
                "full_name": "Synthetic Viewer", "password": PASSWORD, "role": "readonly"}) for index in range(2)]
    tokens = [installation.login(user["username"]) for user in viewers]
    def parallel_read(token):
        for _ in range(8):
            assert installation.request("/api/v1/auth/me", token=token)["role"] == "readonly"
            assert isinstance(installation.request("/api/v1/properties", token=token), list)
        return True
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(parallel_read, tokens))
    installation.request("/api/v1/auth/users/me/preferences", method="PUT", token=tokens[0], data={"theme": "dark", "locale": "es-ES"})
    assert installation.request("/api/v1/auth/users/me/preferences", token=tokens[1])["theme"] == "light"
    installation.request("/api/v1/portfolios", method="POST", token=tokens[0], data={"name": "Forbidden"}, expected=403)

    portfolio = create("/portfolios", {"name": "Synthetic Private Portfolio"})
    prop = create("/properties", {"portfolio_id": portfolio["id"], "name": "Synthetic Building", "property_type": "residential"})
    unit = create("/units", {"property_id": prop["id"], "label": "Synthetic Apartment", "unit_type": "apartment", "area_sqm": 60,
                            "cold_rent": 800, "service_charge_advance": 150, "heating_advance": 50})
    tenant = create("/tenants", {"full_name": "Synthetic Resident"})
    contract = create("/contracts", {"contract_number": "CI-PRIVATE-1", "property_id": prop["id"], "unit_id": unit["id"],
                                    "tenant_id": tenant["id"], "start_date": "2026-01-01"})
    request = {"start_month": "2026-09", "end_month": "2026-09", "contract_ids": [contract["id"]]}
    preview = installation.request("/api/v1/rent-charges/preview", method="POST", token=owner, data=request)
    generated = installation.request("/api/v1/rent-charges/generate", method="POST", token=owner, data={**request, "preview_hash": preview["preview_hash"]})
    assert generated["created_count"] == 1
    charge = generated["created"][0]
    account = create("/accounts", {"portfolio_id": portfolio["id"], "name": "Synthetic Bank", "account_type": "bank"})
    booking = create("/bookings", {"account_id": account["id"], "booking_date": "2026-09-03", "amount": 1000})
    payment = create(f"/rent-charges/{charge['id']}/payments", {"amount": "1000.00", "payment_date": "2026-09-03", "booking_id": booking["id"], "idempotency_key": str(uuid4())})
    assert installation.request(f"/api/v1/rent-charges/{charge['id']}", token=owner)["amount_paid"] == 1000
    reversal = installation.request(f"/api/v1/rent-charges/{charge['id']}/payments/{payment['id']}/reversal", method="POST", token=owner,
                                    data={"idempotency_key": str(uuid4()), "reversal_date": "2026-10-01", "reason": "Synthetic correction"}, expected=201)
    # A second independent cash receipt leaves both original and reversal evidence.
    create(f"/rent-charges/{charge['id']}/payments", {"amount": "40.10", "payment_date": "2026-10-01", "idempotency_key": str(uuid4())})

    boundary = "immo-ci-" + uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.txt\"\r\nContent-Type: text/plain\r\n\r\n".encode()
            + FILE_BYTES + f"\r\n--{boundary}--\r\n".encode())
    file_info = installation.request("/api/v1/files/upload", method="POST", token=owner, raw=body,
                                     headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    file_url = file_info["file_url"]
    assert installation.request(file_url, token=owner) == FILE_BYTES
    installation.request(file_url, expected=401)
    installation.request("/api/v1/integrations/email/config", method="PUT", token=owner,
                         data={"config": {"sender_email": "synthetic@example.invalid", "smtp_host": "unconfigured.invalid"}})
    setup = installation.request("/api/v1/auth/2fa/setup", method="POST", token=owner, data={})
    installation.request("/api/v1/auth/2fa/verify", method="POST", token=owner, data={"code": totp(setup["secret"])})
    return {"charge": charge["id"], "payment": payment["id"], "reversal": reversal["id"], "file": file_url,
            "totp": setup["secret"], "viewer": viewers[0]["id"]}


def verify(installation: Installation, references: dict):
    token = installation.login(secret=references["totp"])
    assert len(installation.request("/api/v1/auth/users", token=token)) == 3
    assert installation.request("/api/v1/auth/setup-status")["setup_required"] is False
    assert installation.request(references["file"], token=token) == FILE_BYTES
    charge = installation.request("/api/v1/rent-charges/" + references["charge"], token=token)
    assert charge["amount_paid"] == 40.1
    receipts = installation.request(f"/api/v1/rent-charges/{references['charge']}/payments", token=token)
    original = next(row for row in receipts if row["id"] == references["payment"])
    assert original["reversal"]["id"] == references["reversal"]
    assert installation.request("/api/v1/integrations/email", token=token)["config"]["smtp_host"] == "unconfigured.invalid"
    viewer_token = installation.login("viewer0")
    assert installation.request("/api/v1/auth/users/me/preferences", token=viewer_token)["locale"] == "es-ES"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="immo-private-acceptance-") as temporary:
        work = Path(temporary)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment = configure(work / "server.env", "https://synthetic.private.example", port)
        source = Installation("immo-private-ci-" + uuid4().hex[:12], environment, port)
        restored = Installation("immo-private-ci-" + uuid4().hex[:12], work / "restored.env", port)
        try:
            source.compose("up", "-d", "--build", "--wait", "app")
            assert source.request("/health")["database_connected"] is True
            assert b'<div id="root"' in source.request("/")
            source.request("/health", headers={"Host": "foreign.invalid", "X-Forwarded-Host": "synthetic.private.example"}, expected=400)
            assert source.request("/api/v1/auth/setup-status")["setup_allowed"] is False
            source.request("/api/v1/auth/setup", method="POST", data={"username": "spoof", "email": "spoof@example.invalid", "full_name": "Spoof", "password": PASSWORD},
                           headers={"X-Forwarded-For": "127.0.0.1", "Origin": source.base}, expected=403)
            owner_arguments = ("exec", "-T", "app", "python", "scripts/server_admin.py", "initial-owner", "--username", "ci_owner",
                               "--email", "owner@example.invalid", "--full-name", "Synthetic Owner", "--password-stdin")
            source.compose(*owner_arguments, input=(PASSWORD + "\n").encode())
            source.compose(*owner_arguments, input=(PASSWORD + "\n").encode(), expected=1)
            references = seed(source, source.login())
            source.compose("up", "-d", "--force-recreate", "--no-deps", "--wait", "app")
            verify(source, references)
            package = work / "private-recovery.immo"
            backup(project=source.project, destination=package, compose_file=ROOT / "compose.private-server.yml",
                   env_file=environment, password=PASSWORD)
            # Backup must resume the source app; validate that independently.
            verify(source, references)
            try:
                restore(project=restored.project, source=package, compose_file=ROOT / "compose.private-server.yml",
                        env_output=restored.environment, password="wrong synthetic recovery passphrase")
            except BackupError:
                pass
            else:
                raise AssertionError("A wrong recovery passphrase must fail.")
            assert not restored.environment.exists()
            # Remove only this script's disposable source, including both volumes.
            # Restoration cannot read source state after this point.
            source.compose("down", "--volumes", "--remove-orphans", timeout=120)
            restore(project=restored.project, source=package, compose_file=ROOT / "compose.private-server.yml",
                    env_output=restored.environment, password=PASSWORD)
            assert restored.request("/health")["database_connected"] is True
            verify(restored, references)
            print("Private PostgreSQL server passed: concurrent users, receipts/reversal, TOTP, preferences, uploads, recreation and encrypted recovery after source deletion.")
        finally:
            if restored.environment.exists():
                restored.compose("down", "--volumes", "--remove-orphans", timeout=120)
            source.compose("down", "--volumes", "--remove-orphans", timeout=120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
