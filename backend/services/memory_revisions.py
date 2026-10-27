"""Recheck edit tokens and replace memory records under the store's writer lock."""

from functools import wraps
from inspect import signature


def atomic_memory_update(table: str | None = None):
    """A fixed collection for PUT methods, or the entity map for `_patch_entity`."""
    def decorate(function):
        parameters = signature(function)
        names = list(parameters.parameters)

        @wraps(function)
        def wrapped(*args, **kwargs):
            # Deferred imports keep the storage/model initialization acyclic.
            from .business_field_history import record_memory_changes
            from .document_versions import memory_archive
            from .record_revisions import assert_expected, consume_expected

            values = parameters.bind(*args, **kwargs).arguments
            store = values[names[0]]
            if table is None:
                entity = values[names[1]]
                collection = store._ENTITY_TYPE_MAP.get(entity)
                if collection is None:
                    return function(*args, **kwargs)  # retain the method's unknown-type error
                collection_name, record_id = collection[0], values[names[2]]
            else:
                collection_name, record_id = table, values[names[1]]
            with memory_archive(store).lock:
                current = getattr(store, collection_name).get(record_id)
                if current is not None:
                    assert_expected(collection_name, record_id, current.updated_at)
                before = current.model_copy(deep=True) if current is not None else None
                result = function(*args, **kwargs)
                try:
                    record_memory_changes(store, collection_name, before, getattr(store, collection_name).get(record_id))
                except BaseException:
                    # The field history and the source replacement form one memory write.
                    if before is not None:
                        getattr(store, collection_name)[record_id] = before
                    raise
                consume_expected(collection_name, record_id)
                return result

        return wrapped
    return decorate
