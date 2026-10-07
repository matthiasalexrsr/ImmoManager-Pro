"""Email notification service using SMTP.

Sends notification emails using configurable SMTP settings.
Reports success only after SMTP accepts the selected recipient.
"""

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


class EmailConfig:
    """SMTP configuration loaded from environment."""

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        smtp_use_tls: bool = True,
        from_address: str = "noreply@immomanager.local",
        from_name: str = "ImmoManager Pro",
        smtp_timeout: float = 10,
        smtp_use_ssl: bool = False,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.smtp_use_tls = smtp_use_tls
        self.from_address = from_address
        self.from_name = from_name
        self.smtp_timeout = smtp_timeout
        self.smtp_use_ssl = smtp_use_ssl

    @property
    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.from_address)


# Module-level config instance (configure via set_email_config)
_config = EmailConfig()


def set_email_config(config: EmailConfig) -> None:
    """Set the global email configuration."""
    global _config
    _config = config


def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
    *,
    config: Optional[EmailConfig] = None,
) -> bool:
    """Send an email via SMTP.

    Returns True if sent successfully, False otherwise.
    An unconfigured or rejected delivery returns False.
    """
    config = config or _config
    if not config.is_configured:
        logger.info(
            "E-Mail (nicht gesendet, SMTP nicht konfiguriert): An=%s, Betreff=%s",
            to, subject,
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{config.from_name} <{config.from_address}>"
    msg["To"] = to

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    server = None
    try:
        server = _connect(config)
        refused = server.send_message(msg, from_addr=config.from_address, to_addrs=[to])
        if refused:
            return False
        logger.info("E-Mail gesendet: An=%s, Betreff=%s", to, subject)
        return True
    except Exception:
        logger.warning("E-Mail-Versand fehlgeschlagen: An=%s", to)
        return False
    finally:
        _disconnect(server)


def _connect(config: EmailConfig):
    context = ssl.create_default_context()
    server = None
    try:
        if config.smtp_use_ssl:
            server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=config.smtp_timeout, context=context)
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.smtp_timeout)
        server.ehlo()
        if config.smtp_use_tls and not config.smtp_use_ssl:
            server.starttls(context=context)
            server.ehlo()
        if config.smtp_user:
            server.login(config.smtp_user, config.smtp_password)
        return server
    except Exception:
        _disconnect(server)
        raise


def _disconnect(server):
    if server is None:
        return
    try:
        server.quit()
    except Exception:
        try:
            server.close()
        except Exception:
            pass


def check_email_connection(config: EmailConfig) -> bool:
    """Authenticate and issue NOOP; never creates or submits an email."""
    if not config.is_configured:
        return False
    server = None
    try:
        server = _connect(config)
        code, _ = server.noop()
        return code == 250
    except Exception:
        logger.warning("SMTP-Verbindungsprüfung fehlgeschlagen")
        return False
    finally:
        _disconnect(server)


def send_notification_email(
    to: str,
    notification_type: str,
    title: str,
    content: str,
) -> bool:
    """Send a notification as an email.

    Wraps the notification content in a simple HTML template.
    """
    severity_colors = {
        "info": "#3b82f6",
        "warning": "#f59e0b",
        "critical": "#ef4444",
    }
    color = severity_colors.get("info", "#3b82f6")

    body_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {color}; color: white; padding: 16px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">{title}</h2>
        </div>
        <div style="padding: 16px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
            <p>{content}</p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 16px 0;">
            <p style="color: #6b7280; font-size: 12px;">
                Diese Nachricht wurde automatisch von ImmoManager Pro generiert.
            </p>
        </div>
    </div>
    """
    return send_email(to, f"[ImmoManager] {title}", body_html, body_text=content)
