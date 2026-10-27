"""Write-only task checks; historic tasks remain readable and repairable."""

from ..storage import NotFoundError, ValidationError


def validate_task_parent(data, get_task, task_id=None):
    if not data.title.strip():
        raise ValidationError("Bitte einen Titel für die Aufgabe angeben.")
    if not data.parent_task_id:
        return
    if task_id is not None and get_task(task_id).parent_task_id == data.parent_task_id:
        return  # unrelated edits do not reinterpret historic links
    visited = {task_id} if task_id else set()
    parent = data.parent_task_id
    while parent:
        if parent in visited:
            raise ValidationError("Eine Aufgabe darf weder direkt noch über Folgeaufgaben von sich selbst abhängen.")
        visited.add(parent)
        try:
            parent = get_task(parent).parent_task_id
        except NotFoundError as error:
            raise ValidationError("Die übergeordnete Aufgabe ist nicht verfügbar.") from error
