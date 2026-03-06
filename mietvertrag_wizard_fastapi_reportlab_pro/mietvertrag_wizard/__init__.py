"""Mietvertrag-Wizard: browserbasierter Wizard + PDF-Export (pdfMake)."""

from .fastapi_integration import mount_fastapi

try:
    from .flask_integration import create_blueprint
except ImportError:  # Flask not installed
    create_blueprint = None  # type: ignore[assignment]

__all__ = ["mount_fastapi", "create_blueprint"]
