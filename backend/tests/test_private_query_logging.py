"""Provider challenges must not escape through request or error diagnostics."""

import logging
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.exceptions import register_exception_handlers
from backend.logging_config import safe_query
from backend.middleware import RequestLoggingMiddleware


def test_sensitive_dotted_and_encoded_query_names_are_redacted_without_losing_filters():
    query = 'hub.verify_token=SYNTHETIC-VERIFY&access%5Ftoken=PRIVATE&apiKey=PRIVATE2&signature=PRIVATE3&filter=offen&filter=neu'
    parsed = parse_qsl(safe_query(query))
    assert parsed[:4] == [(name, '[REDACTED]') for name in ('hub.verify_token', 'access_token', 'apiKey', 'signature')]
    assert parsed[4:] == [('filter', 'offen'), ('filter', 'neu')]
    assert 'PRIVATE' not in safe_query(query)


def test_real_request_and_error_log_contexts_do_not_include_webhook_verification_value(caplog):
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    @app.get('/api/v1/channel-webhooks/whatsapp/synthetic')
    def endpoint():
        raise HTTPException(404, 'Nicht gefunden')

    with caplog.at_level(logging.INFO), TestClient(app) as client:
        result = client.get('/api/v1/channel-webhooks/whatsapp/synthetic?hub.verify_token=SYNTHETIC-VERIFY&hub.challenge=PRIVATE-CHALLENGE')
    assert result.status_code == 404
    diagnostics = [record for record in caplog.records if record.name in ('backend.middleware', 'backend.exceptions')]
    assert len(diagnostics) >= 2
    for record in diagnostics:
        assert 'SYNTHETIC-VERIFY' not in str(getattr(record, 'query', ''))
        assert 'PRIVATE-CHALLENGE' not in str(getattr(record, 'query', ''))
