"""An existing bounded text sample must not become a falsely complete index."""
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401

from backend.db.orm_models import Base, DocumentTextORM
from backend.models import DocumentCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore


@pytest.mark.parametrize("start_revision", ["a9c1e3f5b7d2", "b02a1d3e5f70", None])
def test_upgrade_keeps_old_text_and_marks_it_for_a_resumable_rebuild(tmp_path, start_revision):
    url = f"sqlite:///{(tmp_path / 'old-index.db').as_posix()}"
    engine = sa.create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        portfolio = store.create_portfolio(PortfolioCreate(name="Migrationstest"))
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
        document = store.create_document(DocumentCreate(title="Alter Index", property_id=prop.id, file_url="/uploads/test.txt"))
    # Reproduce exactly the previous derived table; all business tables remain.
    old = sa.MetaData()
    sa.Table("documents", old, autoload_with=engine)
    columns: list[sa.Column] = [
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_ref", sa.Text(), nullable=False), sa.Column("source", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False), sa.Column("indexed_at", sa.DateTime(), nullable=False)]
    if start_revision != "a9c1e3f5b7d2":
        columns += [sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.true()),
                    sa.Column("cursor", sa.JSON(), nullable=False, server_default="{}"),
                    sa.Column("source_sha256", sa.String(64)),
                    sa.Column("indexed_units", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("warning", sa.Text())]
    table = sa.Table("document_texts", old, *columns)
    with engine.begin() as connection:
        derived = DocumentTextORM.__table__
        assert isinstance(derived, sa.Table)
        derived.drop(connection)
        table.create(connection)
        connection.execute(table.insert().values(document_id=document.id, source_ref="file:/uploads/test.txt",
            source="plain", text="Alte Teilmenge", search_text="alte teilmenge", characters=14, indexed_at=datetime(2026, 10, 27)))
        if start_revision is not None:
            version = sa.Table("alembic_version", sa.MetaData(), sa.Column("version_num", sa.String(32), primary_key=True))
            version.create(connection)
            connection.execute(version.insert().values(version_num=start_revision))
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "db/migrations"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with Session(engine) as session:
        row = session.get(DocumentTextORM, document.id)
        assert row is not None
        assert row.text == "Alte Teilmenge" and row.complete is (start_revision != "a9c1e3f5b7d2")
        assert row.cursor == {} and row.source_sha256 is None
        assert row.indexed_units == row.total_units == 0
        assert row.source_updated_at is None
        from backend.services import document_text

        assert document.id in [candidate.id for candidate in document_text.pending(SQLAlchemyStore(session), "", 10)]
    engine.dispose()


def test_postgres_marker_migration_preserves_existing_finished_index(postgres):  # noqa: F811
    from backend.services import document_text

    engine, config = postgres
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        portfolio = store.create_portfolio(PortfolioCreate(name="PG-Migration"))
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
        document = store.create_document(DocumentCreate(title="Bestehender Index", property_id=prop.id,
                                                         file_url="/uploads/legacy.txt"))
        session.add(DocumentTextORM(document_id=document.id, source_ref="file:/uploads/legacy.txt", source="plain",
            text="Alttext", search_text="alttext", characters=7, indexed_at=document_text.now(), complete=True,
            cursor={"offset": 7}, source_sha256="a" * 64, indexed_units=7, total_units=7,
            source_updated_at=document.updated_at))
        session.commit()
    command.downgrade(config, "b02a1d3e5f70")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT text FROM document_texts").scalar_one() == "Alttext"
        assert "source_updated_at" not in {column["name"] for column in sa.inspect(connection).get_columns("document_texts")}
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with Session(engine) as session:
        row = session.get(DocumentTextORM, document.id)
        assert row is not None and row.complete is True and row.text == "Alttext"
        assert row.cursor == {"offset": 7} and row.source_sha256 == "a" * 64 and row.source_updated_at is None
        assert document.id in [candidate.id for candidate in document_text.pending(SQLAlchemyStore(session), "", 10)]
