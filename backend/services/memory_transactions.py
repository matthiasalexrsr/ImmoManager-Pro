"""Serialize memory CRUD with durable multi-record service transactions.

SQL has database transaction locks. Memory must use the same re-entrant lock
for normal store calls and archive units, including inherited store methods.
"""
from collections.abc import MutableMapping
from functools import wraps


class LockedCollection(MutableMapping):
    """Collection reads also wait for a multi-table memory transaction."""
    def __init__(self, store, raw):
        self.store, self.raw = store, raw

    @property
    def lock(self):
        from .document_versions import memory_archive
        return memory_archive(self.store).lock

    def __getitem__(self, key):
        with self.lock:
            return self.raw[key]

    def __setitem__(self, key, value):
        with self.lock:
            self.raw[key] = value

    def __delitem__(self, key):
        with self.lock:
            del self.raw[key]

    def __iter__(self):
        with self.lock:
            return iter(tuple(self.raw))

    def __len__(self):
        with self.lock:
            return len(self.raw)

    def values(self):
        with self.lock:
            return tuple(self.raw.values())

    def items(self):
        with self.lock:
            return tuple(self.raw.items())

    def keys(self):
        with self.lock:
            return tuple(self.raw.keys())

    def clear(self):
        with self.lock:
            self.raw.clear()

    def update(self, *args, **kwargs):
        with self.lock:
            self.raw.update(*args, **kwargs)

    def copy(self):
        with self.lock:
            return dict(self.raw)


def serialized_store(cls):
    def wrap(function):
        @wraps(function)
        def locked(self, *args, **kwargs):
            from .document_versions import memory_archive
            with memory_archive(self).lock:
                if function.__name__.startswith("delete_") and args:
                    from .private_dependencies import ensure_unbound
                    entity = function.__name__.removeprefix("delete_")
                    target = self._ENTITY_TYPE_MAP.get(entity)
                    if target:
                        ensure_unbound(self, target[0], args[0])
                return function(self, *args, **kwargs)
        return locked

    names = set()
    for ancestor in cls.__mro__:
        for name, function in vars(ancestor).items():
            if name in names:
                continue
            names.add(name)
            if callable(function) and (name.startswith(("create_", "get_", "list_", "count_", "update_", "patch_", "delete_")) or name == "clear_all"):
                setattr(cls, name, wrap(function))
    return cls
