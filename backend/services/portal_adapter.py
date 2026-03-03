"""Portal adapter service for publishing listings to external platforms.

Provides an abstract interface for pushing listing data to property portals
like ImmobilienScout24, Immowelt, etc.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PortalPublishResult:
    """Result of publishing a listing to a portal."""
    success: bool
    portal_name: str
    portal_listing_id: Optional[str] = None
    portal_url: Optional[str] = None
    error: Optional[str] = None
    published_at: Optional[datetime] = None


class PortalAdapter(ABC):
    """Abstract base class for property portal integrations."""

    @property
    @abstractmethod
    def portal_name(self) -> str:
        """Return the name of the portal."""
        ...

    @abstractmethod
    def publish(self, listing_data: dict) -> PortalPublishResult:
        """Publish a listing to the portal."""
        ...

    @abstractmethod
    def update(self, portal_listing_id: str, listing_data: dict) -> PortalPublishResult:
        """Update an existing listing on the portal."""
        ...

    @abstractmethod
    def unpublish(self, portal_listing_id: str) -> PortalPublishResult:
        """Remove a listing from the portal."""
        ...

    @abstractmethod
    def check_status(self, portal_listing_id: str) -> dict:
        """Check the status of a listing on the portal."""
        ...


class ImmobilienScout24Adapter(PortalAdapter):
    """Adapter for ImmobilienScout24 (IS24) API.

    Requires API credentials configured via environment variables:
    - IS24_API_KEY
    - IS24_API_SECRET
    - IS24_ACCESS_TOKEN
    """

    @property
    def portal_name(self) -> str:
        return "ImmobilienScout24"

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret

    def publish(self, listing_data: dict) -> PortalPublishResult:
        logger.info("IS24 publish: %s (API not connected)", listing_data.get("title", ""))
        return PortalPublishResult(
            success=False,
            portal_name=self.portal_name,
            error="IS24-API nicht konfiguriert. Bitte API-Schlüssel hinterlegen.",
        )

    def update(self, portal_listing_id: str, listing_data: dict) -> PortalPublishResult:
        return PortalPublishResult(
            success=False, portal_name=self.portal_name,
            error="IS24-API nicht konfiguriert.",
        )

    def unpublish(self, portal_listing_id: str) -> PortalPublishResult:
        return PortalPublishResult(
            success=False, portal_name=self.portal_name,
            error="IS24-API nicht konfiguriert.",
        )

    def check_status(self, portal_listing_id: str) -> dict:
        return {"status": "not_configured", "portal": self.portal_name}


class ImmoweltAdapter(PortalAdapter):
    """Adapter for Immowelt API."""

    @property
    def portal_name(self) -> str:
        return "Immowelt"

    def publish(self, listing_data: dict) -> PortalPublishResult:
        logger.info("Immowelt publish: %s (API not connected)", listing_data.get("title", ""))
        return PortalPublishResult(
            success=False,
            portal_name=self.portal_name,
            error="Immowelt-API nicht konfiguriert.",
        )

    def update(self, portal_listing_id: str, listing_data: dict) -> PortalPublishResult:
        return PortalPublishResult(
            success=False, portal_name=self.portal_name,
            error="Immowelt-API nicht konfiguriert.",
        )

    def unpublish(self, portal_listing_id: str) -> PortalPublishResult:
        return PortalPublishResult(
            success=False, portal_name=self.portal_name,
            error="Immowelt-API nicht konfiguriert.",
        )

    def check_status(self, portal_listing_id: str) -> dict:
        return {"status": "not_configured", "portal": self.portal_name}


# Registry of available portal adapters
_adapters: dict[str, PortalAdapter] = {}


def register_adapter(adapter: PortalAdapter) -> None:
    """Register a portal adapter."""
    _adapters[adapter.portal_name.lower()] = adapter
    logger.info("Portal adapter registered: %s", adapter.portal_name)


def get_adapter(portal_name: str) -> Optional[PortalAdapter]:
    """Get a portal adapter by name."""
    return _adapters.get(portal_name.lower())


def list_adapters() -> list[str]:
    """List all registered portal adapter names."""
    return [a.portal_name for a in _adapters.values()]


# Register default adapters
register_adapter(ImmobilienScout24Adapter())
register_adapter(ImmoweltAdapter())
