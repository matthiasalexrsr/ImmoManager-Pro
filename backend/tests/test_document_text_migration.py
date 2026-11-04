"""An existing bounded text sample must not become a falsely complete index."""
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from backend.db.orm_models import Base, DocumentTextORM
from backend.models import DocumentCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore


def test_upgrade_keeps_old_text_and_marks_it_for_a_resumable_rebuild(tmp_path):
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
    table = sa.Table("document_texts", old,
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id"), primary_key=True),
        sa.Column("source_ref", sa.Text(), nullable=False), sa.Column("source", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False), sa.Column("indexed_at", sa.DateTime(), nullable=False))
    with engine.begin() as connection:
        derived = DocumentTextORM.__table__
        assert isinstance(derived, sa.Table)
        derived.drop(connection)
        table.create(connection)
        connection.execute(table.insert().values(document_id=document.id, source_ref="file:/uploads/test.txt",
            source="plain", text="Alte Teilmenge", search_text="alte teilmenge", characters=14, indexed_at=datetime(2026, 10, 27)))
        version = sa.Table("alembic_version", sa.MetaData(), sa.Column("version_num", sa.String(32), primary_key=True))
        version.create(connection)
        connection.execute(version.insert().values(version_num="a9c1e3f5b7d2"))
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "db/migrations"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with Session(engine) as session:
        row = session.get(DocumentTextORM, document.id)
        assert row is not None
        assert row.text == "Alte Teilmenge" and row.complete is False
        assert row.cursor == {} and row.source_sha256 is None
        assert row.indexed_units == row.total_units == 0
    engine.dispose()
