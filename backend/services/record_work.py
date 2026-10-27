"""Use the existing transaction and account fence for ordinary office workflows."""

from . import document_versions as archive
from .portfolio_scope import current_scope


def record_work(store, area: str):
    scope = current_scope()
    if scope is not None:
        return archive.work(store, scope.user_id, write_areas=(area,))
    # Internal, account-free calls retain the same SQL rollback / memory undo.
    from .maintenance_projects import work
    return work(store, None, (area,))
