"""Mietvertrag-Wizard: browserbasierter Wizard + PDF-Export (pdfMake)."""

from .fastapi_integration import mount_fastapi
from .flask_integration import create_blueprint

__all__ = ["mount_fastapi", "create_blueprint"]
