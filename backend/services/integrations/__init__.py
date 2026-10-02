"""Lazy public manager export keeps offline history validation callback-free."""


def __getattr__(name):
    if name == "integration_manager":
        from .manager import integration_manager

        return integration_manager
    raise AttributeError(name)

__all__ = ["integration_manager"]
