"""A real TLS SMTP NOOP against an owned loopback server, with no message delivery."""

import ipaddress
import socketserver
import ssl
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from backend import auth
from backend.dependencies import store
from backend.services.integrations.connection_runs import ConnectionRuns
from backend.services.integrations.connection_types import ConnectionCreate, RunDispatch, RunPreparation
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import EmailIntegrationProvider
from backend.services.secret_box import SecretBox


@pytest.fixture
def smtp_server(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Owned synthetic SMTP test")])
    moment = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(moment - timedelta(minutes=5))
                   .not_valid_after(moment + timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                   .sign(key, hashes.SHA256()))
    certificate_path = tmp_path / "synthetic-cert.pem"
    key_path = tmp_path / "synthetic-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate_path))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate_path, key_path)
    commands, protocols = [], []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 synthetic.example.test ESMTP fixture\r\n")
            self.wfile.flush()
            for _ in range(12):
                line = self.rfile.readline(16384)
                if not line:
                    return
                verb = line.split(b" ", 1)[0].strip().upper().decode("ascii", errors="replace")
                commands.append(verb)
                if verb in {"EHLO", "HELO"}:
                    self.wfile.write(b"250-synthetic.example.test\r\n250 SIZE 1000000\r\n")
                elif verb == "NOOP":
                    self.wfile.write(b"250 connection healthy; no message accepted\r\n")
                elif verb == "QUIT":
                    self.wfile.write(b"221 closing\r\n")
                    self.wfile.flush()
                    return
                else:
                    self.wfile.write(b"550 this fixture accepts NOOP only\r\n")
                self.wfile.flush()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            secured = context.wrap_socket(connection, server_side=True)
            protocols.append(secured.version())
            return secured, address

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, name="owned-smtp-proof", daemon=True)
    thread.start()
    try:
        yield server.server_address[1], commands, protocols
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        key_path.unlink(missing_ok=True)


def test_real_smtp_noop_uses_verified_tls_and_replay_does_not_repeat_the_probe(tmp_path, smtp_server):
    port, commands, protocols = smtp_server
    auth.clear_users()
    store.clear_all()
    store.__dict__.pop("_integration_connections", None)
    try:
        owner = auth.register_user("smtp-proof", "smtp@example.test", "SMTP-Prüfung", "Secret123", "eigentuemer")
        box = SecretBox(tmp_path / "keyring.json")
        manager = IntegrationManager(secret_box=box)
        manager.register(EmailIntegrationProvider())
        service = ConnectionRuns(store, manager, box)
        connection = service.create(ConnectionCreate(idempotency_key=str(uuid4()), provider_id="email", name="Nur lokale TLS-Prüfung",
            enabled=True, config={"smtp_host": "127.0.0.1", "smtp_port": port, "smtp_use_ssl": True, "smtp_use_tls": False,
                                  "sender_email": "synthetic@example.test", "smtp_timeout": 5}), owner.id)
        run = service.prepare(connection["id"], RunPreparation(idempotency_key=str(uuid4()), config_revision=1,
            action="check_connection", payload={}), owner.id)
        assert commands == [] and protocols == []
        confirm = RunDispatch(idempotency_key=str(uuid4()), base_revision=run["revision"], confirm=True)
        completed = service.dispatch(connection["id"], run["id"], confirm, owner.id)
        assert completed["state"] == "completed"
        assert commands.count("NOOP") == 1 and commands.count("QUIT") == 1
        assert not ({"MAIL", "RCPT", "DATA", "AUTH"} & set(commands))
        assert protocols and all(protocol in {"TLSv1.2", "TLSv1.3"} for protocol in protocols)
        before = list(commands)
        assert service.dispatch(connection["id"], run["id"], confirm, owner.id) == completed
        assert commands == before
    finally:
        auth.clear_users()
        store.clear_all()
        store.__dict__.pop("_integration_connections", None)
