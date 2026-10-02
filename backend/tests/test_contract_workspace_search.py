"""Pure PostgreSQL compilation and actual borrowed SQLite connection proof."""

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from backend.db.booking_order import bytewise_id
from backend.db.orm_models import ContractORM
from backend.services.contract_workspace_search import UnicodeCasefold, casefold_mapping, ensure_sqlite_casefold


def test_sql_unicode_mapping_is_exact_python_casefold_including_expansions():
    originals, folded, expansions = casefold_mapping()
    table = str.maketrans(originals, folded)
    sample = originals + "".join(original for original, _ in expansions)
    result = sample.translate(table)
    for original, replacement in expansions:
        result = result.replace(original, replacement)
    assert result == sample.casefold()
    changed = set(sample)
    assert not any(char in changed for char in folded)
    assert not any(char in changed for _, replacement in expansions for char in replacement)


def test_postgres_compiler_binds_mapping_and_query_without_python_recursion():
    term = "%straße'); DROP TABLE contracts; --%".casefold()
    expression = bytewise_id(UnicodeCasefold(ContractORM.__table__.c.contract_number)).like(term)
    compiled = select(expression).compile(dialect=postgresql.dialect())
    statement = str(compiled)
    assert "translate(" in statement and "replace(" in statement and 'COLLATE "C"' in statement
    assert "FROM contracts" in statement
    assert "DROP TABLE" not in statement and term in compiled.params.values()
    assert "lower(" not in statement and "ILIKE" not in statement


def test_sqlite_function_preserves_borrowed_transaction_and_builtin_lower():
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        connection = session.connection()
        connection.exec_driver_sql("CREATE TABLE synthetic (value TEXT)")
        connection.exec_driver_sql("INSERT INTO synthetic VALUES ('Uncommitted')")
        ensure_sqlite_casefold(session)
        assert session.connection() is connection and connection.in_transaction()
        assert (
            session.scalar(select(func.immo_contract_casefold("ÜBER ÄRGER ÖSTERREICH STRAẞE")))
            == "über ärger österreich strasse"
        )
        assert session.scalar(select(func.lower("ÜBER"))) == "Über"
        assert session.scalar(select(func.immo_contract_casefold(None))) is None
        session.rollback()
        assert session.connection().exec_driver_sql("SELECT COUNT(*) FROM synthetic").scalar_one() == 0
    engine.dispose()
