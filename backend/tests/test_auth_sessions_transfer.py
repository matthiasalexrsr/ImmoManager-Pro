"""A business subset restore cannot roll back independent authentication history."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.orm_models import Base, UserORM
from backend.db.session_models import AuthRefreshORM, AuthSessionORM
from backend.models import PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import auth_sessions as service
from backend.services.data_transfer import export_store_data, import_store_data


def test_actual_business_replacement_keeps_consumed_and_revoked_security_state(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "synthetic transfer.sqlite").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    # A historical owner with no portfolio grant rows: the business restore
    # must not rewrite account authentication state or create access grants.
    with engine.begin() as connection:
        connection.execute(UserORM.__table__.insert(), dict(id="legacy-owner", username="legacy-owner",
            email="owner@example.test", full_name="Synthetic", hashed_password="synthetic-unused-hash",
            role="eigentuemer", is_active=True, totp_enabled=False))
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    try:
        original = service.login_pair("legacy-owner")
        current = service.rotate(original.refresh_token)
        with pytest.raises(HTTPException):
            service.rotate(original.refresh_token)
        with factory() as db:
            store = SQLAlchemyStore(db)
            store.create_portfolio(PortfolioCreate(name="Synthetic source"))
            package = export_store_data(store, "synthetic")
            before = {table.name: db.execute(select(table)).all()
                for table in (AuthSessionORM.__table__, AuthRefreshORM.__table__)}
            import_store_data(store, package, replace_existing=True)
            after = {table.name: db.execute(select(table)).all()
                for table in (AuthSessionORM.__table__, AuthRefreshORM.__table__)}
            assert before == after and len(store.list_portfolios()) == 1
        with pytest.raises(HTTPException) as invalid:
            auth.decode_token(current.access_token)
        assert invalid.value.status_code == 401
    finally:
        engine.dispose()
