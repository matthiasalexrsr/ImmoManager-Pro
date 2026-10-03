"""Pure early import boundary; keep ownership through the process lifetime."""

from .runtime import application_import_fence

# Import this module before auth/config/dependencies can start a writer. Module
# caching shares the receipt between direct dependency and ASGI entry points.
# Never release it after import or lifespan: a direct ASGI process is still alive.
APPLICATION_IMPORT_LEASE = application_import_fence()
