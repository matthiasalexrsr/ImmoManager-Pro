"""Errors both stores raise (re-exported by backend.storage, where callers import them)."""


class NotFoundError(KeyError):
    pass


class ValidationError(ValueError):
    pass
