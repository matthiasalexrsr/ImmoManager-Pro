"""Seed field changes only in the isolated browser runner's verified database."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def seed(manifest_path):
    directory = Path(os.environ["DATA_DIR"]).resolve()
    database = make_url(os.environ["DATABASE_URL"])
    if (os.environ.get("ENVIRONMENT") != "development" or directory.parent != Path(tempfile.gettempdir()).resolve()
            or not directory.name.startswith("immomanager-browser-") or database.drivername != "sqlite"
            or Path(database.database or "").resolve() != directory / "immo_manager.db"
            or manifest_path.resolve() != directory / "history-fixture.json"):
        raise RuntimeError("History fixture requires the exact runner-owned temporary database")
    from backend.db.orm_models import ChangeHistoryORM
    from backend.models import PortfolioCreate, PropertyCreate
    from backend.repositories.sql_store import SQLAlchemyStore

    tag = uuid4().hex[:8]
    count = 10002  # Acceptance workload, never a product limit.
    prefix = "B-History " + tag + " "
    long_value = "Vollständiger ursprünglicher Wert äöü — mit nachvollziehbarer Begründung. " * 35
    engine = create_engine(database, hide_parameters=True)
    try:
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            portfolio = store.create_portfolio(PortfolioCreate(name="History browser " + tag))
            prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="History property " + tag, property_type="residential"))
            stamp = datetime(2026, 10, 3, 10, 0, 0, 123456, tzinfo=timezone.utc)
            for start in range(0, count, 500):
                session.execute(ChangeHistoryORM.__table__.insert(), [dict(id=f"history-{tag}-{number:06d}",
                    entity_type="property", entity_id=prop.id, field_name="name", old_value=long_value if number == count - 1 else "=1+1" if number == 7 else "vorher",
                    new_value=f"{prefix}{number:06d}", reason="Synthetic browser acceptance", changed_by="synthetic-actor",
                    changed_at=stamp) for number in range(start, min(count, start + 500))])
            session.commit()
            manifest_path.write_text(json.dumps({"basis": "native-owned-history-stock", "tag": tag, "prefix": prefix,
                "portfolio_id": portfolio.id, "property_id": prop.id, "count": count, "long_value": long_value}), encoding="utf-8")
    finally:
        engine.dispose()
    print("Native synthetic history seeded: 10002 entries in the owned browser fixture")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Pass the runner-owned manifest path")
    seed(Path(sys.argv[1]))
