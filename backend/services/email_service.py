"""SMTP submission with explicit config, bounded workers, and safe outcomes."""
from __future__ import annotations

import math
import multiprocessing as mp
import re
import smtplib
import ssl
import time
from contextvars import ContextVar
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from html import escape
from threading import BoundedSemaphore
from uuid import uuid4

MAX_MESSAGE_BYTES = 1024 * 1024
_SLOTS = BoundedSemaphore(4)
_MAILBOX = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\Z")


class EmailConfigError(ValueError):
    """Only fixed error codes; never include configuration values."""


def _text(value, limit=1024):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise EmailConfigError("invalid_config")
    return value


def _header(value, limit=512):
    value = _text(value, limit)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise EmailConfigError("invalid_header")
    return value


def _mailbox(value):
    value = _header(value, 254)
    if not _MAILBOX.fullmatch(value):
        raise EmailConfigError("invalid_address")
    local, domain = value.rsplit("@", 1)
    if (len(local) > 64 or local.startswith(".") or local.endswith(".")
            or ".." in local or any(not p or p.startswith("-") or p.endswith("-")
                                   or len(p) > 63 for p in domain.split("."))):
        raise EmailConfigError("invalid_address")
    return value


def _boolean(value):
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise EmailConfigError("invalid_config")


@dataclass(frozen=True, repr=False)
class EmailConfig:
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    from_address: str = "noreply@immomanager.local"
    from_name: str = "ImmoManager Pro"
    smtp_use_ssl: bool = False
    timeout_seconds: float = 20.0

    def validate(self):
        host = _header(self.smtp_host, 253)
        if not host or not self.from_address:
            raise EmailConfigError("not_configured")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", host):
            raise EmailConfigError("invalid_config")
        if type(self.smtp_port) is not int or not 1 <= self.smtp_port <= 65535:
            raise EmailConfigError("invalid_config")
        if type(self.smtp_use_tls) is not bool or type(self.smtp_use_ssl) is not bool:
            raise EmailConfigError("invalid_config")
        if self.smtp_use_tls and self.smtp_use_ssl:
            raise EmailConfigError("invalid_config")
        if (isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds)
                or not 1 <= self.timeout_seconds <= 60):
            raise EmailConfigError("invalid_config")
        _mailbox(self.from_address)
        _header(self.from_name)
        _header(self.smtp_user, 1024)
        _text(self.smtp_password, 4096)
        if bool(self.smtp_user) != bool(self.smtp_password) or self.smtp_password == "***":
            raise EmailConfigError("not_configured")
        if self.smtp_user and not (self.smtp_use_tls or self.smtp_use_ssl):
            raise EmailConfigError("plaintext_auth_forbidden")
        return self

    @property
    def is_configured(self):
        try:
            self.validate()
            return True
        except EmailConfigError:
            return False

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, dict):
            raise EmailConfigError("invalid_config")
        try:
            port = values.get("smtp_port", 587)
            timeout = values.get("smtp_timeout_seconds", 20)
            if isinstance(port, bool) or isinstance(timeout, bool):
                raise ValueError
            return cls(
                smtp_host=values.get("smtp_host", ""),
                smtp_port=int(str(port)),
                smtp_user=values.get("smtp_user", ""),
                smtp_password=values.get("smtp_password", ""),
                smtp_use_tls=_boolean(values.get("smtp_use_tls", True)),
                smtp_use_ssl=_boolean(values.get("smtp_use_ssl", False)),
                from_address=values.get("sender_email", ""),
                from_name=values.get("sender_name", "ImmoManager Pro"),
                timeout_seconds=float(timeout),
            ).validate()
        except (TypeError, ValueError, OverflowError):
            raise EmailConfigError("invalid_or_missing_config") from None


SMTPConfig = EmailConfig
_DEFAULT = ContextVar("legacy_email_config", default=EmailConfig())


def set_email_config(config: EmailConfig):
    """Legacy compatibility: context-local, never a process-wide account switch."""
    if not isinstance(config, EmailConfig):
        raise EmailConfigError("invalid_config")
    return _DEFAULT.set(config)


@dataclass(frozen=True)
class EmailResult:
    status: str
    code: str

    @property
    def accepted(self):
        return self.status == "accepted"

    def __bool__(self):
        return self.accepted


def _wire_message(config, to, subject, body_html, body_text):
    _mailbox(to)
    _header(subject)
    for body in (body_html, body_text):
        if body is not None:
            _text(body, MAX_MESSAGE_BYTES)
    if not isinstance(body_html, str):
        raise EmailConfigError("invalid_message")
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = formataddr((config.from_name, config.from_address))
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = f"<{uuid4().hex}@immomanager.invalid>"
    message.set_content(body_text or "", cte="quoted-printable")
    message.add_alternative(body_html, subtype="html", cte="quoted-printable")
    wire = message.as_bytes()
    if len(wire) > MAX_MESSAGE_BYTES:
        raise EmailConfigError("message_too_large")
    return wire


def _smtp_exchange(config, recipient, wire):
    """Runs only in the disposable worker; tests replace both SMTP factories."""
    client: smtplib.SMTP | None = None
    submitting = False
    try:
        context = ssl.create_default_context()
        options = {"timeout": min(config.timeout_seconds, 10.0),
                   "local_hostname": "immomanager.local"}
        if config.smtp_use_ssl:
            client = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port,
                                     context=context, **options)
        else:
            client = smtplib.SMTP(config.smtp_host, config.smtp_port, **options)
        client.set_debuglevel(0)
        client.ehlo_or_helo_if_needed()
        if config.smtp_use_tls:
            client.starttls(context=context)  # No downgrade or certificate bypass.
            code, _ = client.ehlo()
            if code != 250:
                return EmailResult("not_sent", "smtp_greeting_rejected")
        if config.smtp_user:
            client.login(config.smtp_user, config.smtp_password)
        submitting = True
        refused = client.sendmail(config.from_address, [recipient], wire)
        if refused:
            return EmailResult("not_sent", "recipient_rejected")
        return EmailResult("accepted", "smtp_accepted")
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError):
        return EmailResult("not_sent", "smtp_rejected")
    except smtplib.SMTPAuthenticationError:
        return EmailResult("not_sent", "authentication_failed")
    except (smtplib.SMTPNotSupportedError, ssl.SSLError):
        return EmailResult("unknown" if submitting else "not_sent", "tls_or_protocol_failed")
    except Exception:
        # No exception text, credentials, addresses, subject or body in logs/results.
        return EmailResult("unknown" if submitting else "not_sent", "transport_failed")
    finally:
        if client is not None:
            try:
                # Do not let a failed/hanging QUIT turn accepted DATA into a retry.
                client.close()
            except Exception:
                pass


def _smtp_worker(connection, config, recipient, wire):
    try:
        result = _smtp_exchange(config, recipient, wire)
        connection.send((result.status, result.code))
    except Exception:
        try:
            connection.send(("unknown", "worker_failed"))
        except Exception:
            pass
    finally:
        connection.close()


def _bounded_exchange(config, recipient, wire, *, context=None):
    """Wall-clock watchdog includes DNS/TLS/SMTP; no timed-out sender thread remains."""
    context = context or mp.get_context("spawn")
    deadline = time.monotonic() + config.timeout_seconds
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_smtp_worker,
                              args=(writer, config, recipient, wire), daemon=True)
    started = False
    try:
        process.start()
        started = True
        writer.close()
        if reader.poll(max(0.0, deadline - time.monotonic())):
            status, code = reader.recv()
            return EmailResult(status, code)
        return EmailResult("unknown", "deadline_exceeded")
    except Exception:
        return EmailResult("unknown" if started else "not_sent", "worker_failed")
    finally:
        reader.close()
        writer.close()
        if started:
            process.join(0.05)
            if process.is_alive():
                process.kill()
                process.join(0.5)
            if process.is_alive():
                # Fail loudly with a fixed message; do not claim cancellation.
                raise RuntimeError("smtp_worker_cleanup_failed") from None
            process.close()


def submit_email(to, subject, body_html, body_text=None, *, config=None):
    """Structured API: accepted means relay acceptance, never confirmed delivery."""
    selected = config if config is not None else _DEFAULT.get()
    try:
        if not isinstance(selected, EmailConfig):
            raise EmailConfigError("invalid_config")
        selected.validate()
        wire = _wire_message(selected, to, subject, body_html, body_text)
    except (TypeError, ValueError, UnicodeError):
        return EmailResult("not_sent", "invalid_or_missing_config_or_message")
    if not _SLOTS.acquire(blocking=False):
        return EmailResult("not_sent", "busy")
    try:
        return _bounded_exchange(selected, to, wire)
    finally:
        _SLOTS.release()


def send_email(to, subject, body_html, body_text=None, *, config=None) -> bool:
    """Legacy bool API. False also includes unknown; never auto-retry on this bool."""
    return submit_email(to, subject, body_html, body_text, config=config).accepted


def send_notification_email(to, notification_type, title, content, *, config=None) -> bool:
    if not isinstance(title, str) or not isinstance(content, str):
        return False
    body = f"<h2>{escape(title)}</h2><p>{escape(content)}</p>"
    return send_email(to, f"[ImmoManager] {title}", body, content, config=config)
