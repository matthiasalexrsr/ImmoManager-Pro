"""Scope existing comma-separated reference fields without global ID scans."""

from sqlalchemy import Boolean, String, cast, literal_column, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.util import ClauseAdapter
from sqlalchemy.sql.visitors import InternalTraversal


class CSVReferencesVisible(ColumnElement):
    type = Boolean()
    inherit_cache = False
    _traverse_internals = [
        ("field", InternalTraversal.dp_clauseelement),
        ("parent_query", InternalTraversal.dp_clauseelement),
    ]

    def __init__(self, field, parent, criterion):
        self.field = field
        alias = parent.alias()
        adapted = ClauseAdapter(alias).traverse(criterion)
        # Keep the inner SELECT as real SQLAlchemy structure. Its nested grants
        # must correlate to this exact parent, rather than any accessible parent.
        self.parent_query = select(1).select_from(alias).where(
            cast(alias.c.id, String) == literal_column("trim(scope_ref.value)"), adapted,
        )

    @property
    def _from_objects(self):
        # Parent aliases exist only inside the compiled correlated EXISTS.
        return self.field._from_objects


@compiles(CSVReferencesVisible)
def _compile_references(element, compiler, **kwargs):
    field = compiler.process(element.field, **kwargs)
    parent_query = compiler.process(element.parent_query, **kwargs)
    if compiler.dialect.name == "sqlite":
        # json_quote escapes old data; only delimiter commas create elements.
        source = f"json_each('[' || replace(json_quote(coalesce({field}, '')), ',', '\",\"') || ']') AS scope_ref"
    elif compiler.dialect.name in {"postgresql", "default"}:
        source = f"unnest(string_to_array(coalesce({field}, ''), ',')) AS scope_ref(value)"
    else:
        raise RuntimeError("Portfolio-Referenzen unterstützen SQLite und PostgreSQL")
    return (
        f"NOT EXISTS (SELECT 1 FROM {source} WHERE trim(scope_ref.value) <> '' "
        f"AND NOT EXISTS ({parent_query}))"
    )


CSV_PARENTS = {"message_threads": {"participant_ids": "contacts"}, "messages": {"attachment_ids": "documents"}}


def csv_parents(table):
    return CSV_PARENTS.get(table.name, {})


def reference_ids(value):
    return [part.strip() for part in (value or "").split(",") if part.strip()]
