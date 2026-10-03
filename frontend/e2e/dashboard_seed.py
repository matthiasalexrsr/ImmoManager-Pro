"""B2 fixture support: native synthetic SQL rows in the existing runner's temp DB."""

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


def seed(manifest_path: Path) -> None:
    directory = Path(os.environ["DATA_DIR"]).resolve()
    database = make_url(os.environ["DATABASE_URL"])
    if (
        os.environ.get("ENVIRONMENT") != "development"
        or directory.parent != Path(tempfile.gettempdir()).resolve()
        or not directory.name.startswith("immomanager-browser-")
        or database.drivername != "sqlite"
        or Path(database.database or "").resolve() != directory / "immo_manager.db"
        or manifest_path.resolve() != directory / "dashboard-fixture.json"
    ):
        raise RuntimeError("Dashboard fixture requires its exact runner-owned temporary database")
    # Import only after the concrete temporary path has been verified. The runner
    # already migrated and started the native app; this helper performs no DDL.
    from backend.db.orm_models import UnitORM
    from backend.models import PortfolioCreate, PropertyCreate, Unit
    from backend.repositories.sql_store import SQLAlchemyStore

    tag = uuid4().hex[:8]
    amount = 10_001  # Synthetic acceptance workload; never a product stock limit.
    engine = create_engine(database, hide_parameters=True)
    try:
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            portfolio = store.create_portfolio(PortfolioCreate(name=f"B2 large authorized {tag}"))
            prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id,
                name=f"B2 property {tag} " + "ObjectContext" * 12, property_type="residential"))
            stamp = datetime.now(timezone.utc)
            statuses = ("occupied", "rented", "vacant", "reserved", "maintenance")
            rows = [Unit(id=f"b2-stock-{tag}-{index:05d}", property_id=prop.id,
                label=f"B2 unit {index} {tag} " + "LongReference" * 9,
                unit_type="apartment", status=statuses[index % 5], created_at=stamp, updated_at=stamp)
                for index in range(amount)]
            session.execute(UnitORM.__table__.insert(), [row.model_dump() for row in rows])
            session.commit()
            groups = [amount // 5 + int(amount % 5 > index) for index in range(5)]
            manifest = {
                "basis": "native-owned-b2-synthetic-stock",
                "tag": tag,
                "portfolio": portfolio.model_dump(mode="json"),
                "property": prop.model_dump(mode="json"),
                "unitRows": [row.model_dump(mode="json") for row in rows[:13]],
                "lastUnit": rows[-1].model_dump(mode="json"),
                "expected": dict(total=amount, occupied=groups[0] + groups[1], rented=groups[1],
                    vacant=groups[2], reserved=groups[3], other=groups[4]),
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    finally:
        engine.dispose()
    print(f"B2 native synthetic stock seeded: {amount} units; bounded fixture manifest written")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Pass the runner-owned fixture manifest path")
    seed(Path(sys.argv[1]))
