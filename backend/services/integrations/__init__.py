"""Integration namespace without eager side effects while loading provider contracts.

Providers may import integrations.base directly. The package import must not
construct the global IntegrationManager before those classes have been defined.
The existing public integration_manager export remains available on demand.
"""
__all__ = ["integration_manager"]


def __getattr__(name: str):
    if name == "integration_manager":
        from .manager import integration_manager
        return integration_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
