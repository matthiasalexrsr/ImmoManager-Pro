"""Real TLS protocol fixtures bound to ephemeral loopback ports; no account actions."""
import ipaddress
import socketserver
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from backend.services.communication_transport import IMAPReadonly, SMTPTransport


@pytest.fixture
def tls(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                   .not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), True).sign(key, hashes.SHA256()))
    cert = tmp_path / 'fixture-cert.pem'
    private = tmp_path / 'fixture-key.pem'
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, private)
    client = ssl.create_default_context(cafile=str(cert))
    assert client.verify_mode == ssl.CERT_REQUIRED and client.check_hostname
    return server, client


@contextmanager
def local_tls(handler, context):
    with socketserver.TCPServer(('127.0.0.1', 0), handler) as server:
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1]
        finally:
            server.shutdown()
            thread.join(timeout=3)


def test_real_smtp_implicit_tls_preserves_mime_and_verifies_certificate(tls, monkeypatch):
    captured = []
    class Server(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b'220 fixture TLS ESMTP\r\n')
            while line := self.rfile.readline():
                verb = line.split()[0].upper()
                if verb == b'DATA':
                    self.wfile.write(b'354 send\r\n')
                    raw = bytearray()
                    while (part := self.rfile.readline()) != b'.\r\n':
                        if not part:
                            return
                        raw.extend(part[1:] if part.startswith(b'..') else part)
                    captured.append(bytes(raw))
                    self.wfile.write(b'250 fixture TLS accepted\r\n')
                elif verb == b'QUIT':
                    self.wfile.write(b'221 bye\r\n')
                    return
                else:
                    self.wfile.write(b'250 fixture\r\n')
    server_context, client_context = tls
    monkeypatch.setattr(ssl, 'create_default_context', lambda: client_context)
    raw = b'From: sender@example.test\r\nTo: recipient@example.test\r\nMessage-ID: <tls@example.test>\r\n\r\nOriginal body\r\n.dot\r\n'
    with local_tls(Server, server_context) as port:
        transport = SMTPTransport()
        try:
            transport.prepare(dict(smtp_host='127.0.0.1', smtp_port=port, smtp_use_ssl=True, smtp_use_tls=False), 'sender@example.test', ['recipient@example.test'])
            assert transport.server is not None
            assert transport.server.sock.version() in ('TLSv1.2', 'TLSv1.3')
            assert transport.data(raw) == 'accepted'
        finally:
            transport.close()
    assert captured == [raw]
    assert client_context.verify_mode == ssl.CERT_REQUIRED and client_context.check_hostname


def test_real_imap_tls_reads_original_and_never_marks_seen(tls, monkeypatch):
    seen = []
    raw = b'Message-ID: <tls-inbox@example.test>\r\n\r\nOriginal\x00\xff\r\n'
    class Server(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b'* OK fixture TLS IMAP\r\n')
            while line := self.rfile.readline():
                text = line.decode('ascii').strip()
                seen.append(text)
                tag, verb, *args = text.split()
                if verb == 'CAPABILITY':
                    self.wfile.write(b'* CAPABILITY IMAP4rev1\r\n')
                elif verb == 'EXAMINE':
                    self.wfile.write(b'* 1 EXISTS\r\n* OK [UIDVALIDITY 31] valid\r\n* OK [UIDNEXT 2] next\r\n')
                elif verb == 'UID':
                    if 'BODY.PEEK[]' in text:
                        self.wfile.write(f'* 1 FETCH (UID 1 BODY[] {{{len(raw)}}}\r\n'.encode() + raw + b')\r\n')
                    elif 'RFC822.SIZE' in text:
                        self.wfile.write(f'* 1 FETCH (UID 1 RFC822.SIZE {len(raw)})\r\n'.encode())
                    else:
                        self.wfile.write(b'* 1 FETCH (UID 1)\r\n')
                elif verb == 'LOGOUT':
                    self.wfile.write(b'* BYE fixture\r\n' + tag.encode() + b' OK logout\r\n')
                    return
                self.wfile.write(tag.encode() + b' OK done\r\n')
    server_context, client_context = tls
    monkeypatch.setattr(ssl, 'create_default_context', lambda: client_context)
    with local_tls(Server, server_context) as port:
        with IMAPReadonly(dict(imap_host='127.0.0.1', imap_port=port, imap_user='fixture', imap_password='fixture-only')) as adapter:
            assert adapter.server.sock.version() in ('TLSv1.2', 'TLSv1.3')
            assert adapter.uidvalidity() == 31
            assert adapter.next_uids(0) == ([1], 1, False)
            assert adapter.raw(1, 10000) == raw
    assert any(' EXAMINE ' in line for line in seen)
    assert any('BODY.PEEK[]' in line for line in seen)
    assert not any(' STORE ' in line or ' CLOSE' in line or ' EXPUNGE' in line or ' SELECT ' in line for line in seen)
    assert client_context.verify_mode == ssl.CERT_REQUIRED and client_context.check_hostname
