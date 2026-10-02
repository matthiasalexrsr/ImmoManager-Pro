"""Actual TLS/SMTP child handshake, durable DATA permission, watchdog cleanup."""

import multiprocessing as mp
import time
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from backend.services import email_service as mail
from backend.services import outbox
from backend.tests import test_smtp_loopback as loopback
from backend.tests.test_outbox_journal import active as active
from backend.tests.test_outbox_journal import command, review

tls = loopback.tls
servers = loopback.servers


def prepared(server):
    config = mail.EmailConfig.from_mapping(server.config | {"smtp_timeout_seconds": 2})
    wire = mail._wire_message(config, server.payload["recipient"], "Synthetic reviewed message", "<p>Synthetic</p>", "Synthetic",
        message_id="<synthetic-stable@immomanager.invalid>", date_header="Thu, 01 Oct 2026 12:00:00 GMT")
    return config, wire


def test_real_tls_relay_receives_exact_reviewed_wire_after_durable_sql_checkpoint(active, tls, servers, monkeypatch):
    server = servers()
    monkeypatch.setenv("SSL_CERT_FILE", str(tls[0]))
    active.values.update(server.config | {"sender_name": "Synthetic owner", "smtp_timeout_seconds": 4})
    message = outbox.create_message(active.store, review(recipient=server.payload["recipient"], sender_address=server.config["sender_email"]), "actor")
    monkeypatch.setattr(mail, "submit_prepared_email", _original_prepared)
    result = outbox.send_message(active.store, message["id"], command(message), "actor")
    assert result["state"] == "sent" and result["last_code"] == "smtp_accepted"
    row = server.rows[0]
    assert row["closed"].wait(2) and row["accepted"] and row["tls"]
    assert row["sender"] == message["snapshot"]["sender_address"] and row["recipient"] == message["snapshot"]["recipient"]
    parsed = BytesParser(policy=policy.default).parsebytes(row["wire"])
    assert parsed["Message-ID"] == message["message_id"] and not server.errors
    assert not mp.active_children()


# Preserve the real implementation before the unit fixture patches it.
_original_prepared = mail.submit_prepared_email


@pytest.mark.parametrize("fault", ["auth", "rcpt"])
def test_rejected_envelope_is_safe_and_never_requests_data_checkpoint(tls, servers, monkeypatch, fault):
    server = servers(fault=fault)
    monkeypatch.setenv("SSL_CERT_FILE", str(tls[0]))
    config, wire = prepared(server)
    checkpoint = []
    result = _original_prepared(server.payload["recipient"], wire, config=config, before_data=lambda: checkpoint.append(True))
    assert result.status == "not_sent" and checkpoint == []
    assert server.rows[0]["closed"].wait(2) and server.rows[0]["wire"] == b""
    assert not mp.active_children()


def test_denied_checkpoint_closes_child_before_body_submission(tls, servers, monkeypatch):
    server = servers()
    monkeypatch.setenv("SSL_CERT_FILE", str(tls[0]))
    config, wire = prepared(server)
    def denied():
        raise RuntimeError("Synthetic permission revoked")
    result = _original_prepared(server.payload["recipient"], wire, config=config, before_data=denied)
    assert result.status == "not_sent" and result.code == "data_not_authorized"
    assert server.rows[0]["closed"].wait(2) and server.rows[0]["wire"] == b"" and not server.rows[0]["accepted"]
    assert not mp.active_children()


@pytest.mark.parametrize("fault", ["hang", "drip"])
def test_missing_final_data_ack_is_unknown_and_worker_is_gone(tls, servers, monkeypatch, fault):
    server = servers(fault=fault)
    monkeypatch.setenv("SSL_CERT_FILE", str(tls[0]))
    config, wire = prepared(server)
    checkpoint = []
    start = time.monotonic()
    result = _original_prepared(server.payload["recipient"], wire, config=config, before_data=lambda: checkpoint.append(True))
    assert result.status == "unknown" and result.code == "deadline_exceeded" and checkpoint == [True]
    assert time.monotonic() - start < 4
    assert server.rows[0]["closed"].wait(2) and server.rows[0].get("data_complete")
    assert not mp.active_children()


def test_context_creation_failure_releases_transport_slot(tls, servers):
    server = servers()
    config, wire = prepared(server)
    class Broken:
        def Pipe(self, **_):
            raise OSError("Synthetic OS resource failure")
    for _ in range(8):
        result = _original_prepared(server.payload["recipient"], wire, config=config, before_data=lambda: None, context=Broken())
        assert result.status == "not_sent" and result.code == "worker_failed"
    assert server.rows == [] and not mp.active_children()


@pytest.mark.parametrize("reply", [251, 354])
def test_nonstandard_positive_final_data_reply_is_never_safe_to_repeat(monkeypatch, reply):
    client = SimpleNamespace(set_debuglevel=lambda _: None, ehlo_or_helo_if_needed=lambda: None,
        has_extn=lambda _: False, mail=lambda *_: (250, b"ok"), rcpt=lambda _: (250, b"ok"),
        data=lambda _: (reply, b"Synthetic nonstandard reply"), close=lambda: None)
    monkeypatch.setattr(mail.smtplib, "SMTP", lambda *_, **__: client)
    config = mail.EmailConfig(smtp_host="127.0.0.1", smtp_use_tls=False, from_address="synthetic@test.invalid")
    result = mail._smtp_exchange(config, "recipient@test.invalid", b"Synthetic MIME", before_data=lambda: True)
    assert result.status == "unknown" and result.code == "unexpected_data_reply"
