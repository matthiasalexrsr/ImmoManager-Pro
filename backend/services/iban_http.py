"""Explicit application integration for safe, repairable encryption failures."""

import logging

from fastapi.responses import JSONResponse

from ..logging_config import request_id_var
from .iban_encryption import IBANEncryptionError

logger = logging.getLogger(__name__)


def register_iban_exception_handler(app):
    @app.exception_handler(IBANEncryptionError)
    async def unavailable(request, exc):
        logger.error("Account encryption unavailable: code=%s request_id=%s", exc.code, request_id_var.get())
        return JSONResponse(
            status_code=503,
            content=dict(
                error=dict(
                    code=exc.code,
                    message="Bankverbindung kann nicht verlässlich gelesen oder gespeichert werden.",
                    recovery=exc.recovery,
                    request_id=request_id_var.get() or "-",
                )
            ),
        )
