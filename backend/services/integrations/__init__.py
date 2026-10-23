"""Integration API without initializing providers during a provider import.

Providers import the shared contracts in this package. Eagerly constructing the
manager here would import those same, only partially initialized providers.
"""


def __getattr__(name):
    if name == "integration_manager":
        from .manager import integration_manager

        return integration_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["integration_manager"]
