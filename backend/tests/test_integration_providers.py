"""Tests for integration provider adapters."""

from backend.services.integrations import providers
from backend.services.integrations.providers import EmailIntegrationProvider


def test_email_provider_calls_send_email_with_its_signature(monkeypatch):
    calls = []

    def fake_send_email(to, subject, body_html, body_text=None, *, config=None):
        assert config.smtp_host == "smtp.example.com"
        assert config.from_address == "s@example.com"
        calls.append((to, subject, body_html))
        return True

    monkeypatch.setattr(providers, "send_email", fake_send_email)
    result = EmailIntegrationProvider().run(
        {"recipient": "a@example.com", "subject": "Hi", "body": "<p>x</p>"},
        {"sender_email": "s@example.com", "smtp_host": "smtp.example.com"},
    )

    assert result.success
    assert calls == [("a@example.com", "Hi", "<p>x</p>")]
