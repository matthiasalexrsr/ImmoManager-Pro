"""Native disposable PostgreSQL integration; never substitute SQLite for PG."""

import hashlib
import time
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import auth
from backend.db.auth_models import AuthSetupORM
from backend.db.session_models import AuthSessionORM
from backend.services import contract_lifecycle as lifecycle
from backend.services.recovery_sessions import SessionRestoreError, invalidate_and_inspect
from backend.tests.test_contract_lifecycle import confirmation, prepare
from backend.tests.test_contract_lifecycle_application import rent_confirmation_race, reset_writer_race
from backend.tests.test_contract_lifecycle_postgres import postgres as postgres


def test_actual_postgresql_direct_rent_competes_with_confirmation(postgres):
    rent_confirmation_race(postgres)


@pytest.mark.parametrize("user_store_kind", ["memory", "sql"])
def test_actual_postgresql_reset_waits_for_new_command_then_refuses_before_dml(postgres, monkeypatch, user_store_kind):
    with Session(postgres.engine) as db:
        db.add(AuthSetupORM(id=1))
        db.commit()
        original_marker = db.get(AuthSetupORM, 1).completed_at
    user_store = auth.InMemoryUserStore() if user_store_kind == "memory" else auth.SQLUserStore(lambda: Session(postgres.engine))
    monkeypatch.setattr(auth, "_user_store", user_store)
    reset_writer_race(postgres, monkeypatch)
    with Session(postgres.engine) as db:
        assert db.get(AuthSetupORM, 1).completed_at == original_marker


def test_actual_postgresql_complete_journal_is_verified_before_security_mutation(postgres):
    reviewed = prepare(postgres)
    lifecycle.confirm_draft(postgres.store, postgres.contract.id, reviewed["id"], confirmation(reviewed), "actor")
    family = str(uuid4())
    stamp = datetime(2026, 10, 2)
    with Session(postgres.engine) as db:
        db.add(AuthSessionORM(id=family, user_id="actor", device_label="Synthetic journal family", created_at=stamp,
            last_used_at=stamp, expires_at=stamp + timedelta(days=5), generation=0,
            current_refresh_hash=hashlib.sha256(b"synthetic-family-reference").hexdigest()))
        db.commit()
    # Corrupt only this generated UUID schema, preserving its immutability
    # guards afterward; the offline security boundary must refuse this image.
    with postgres.engine.begin() as db:
        db.exec_driver_sql("ALTER TABLE contract_lifecycle_commands DISABLE TRIGGER USER")
        db.exec_driver_sql("DELETE FROM contract_lifecycle_commands WHERE operation='confirm'")
        db.exec_driver_sql("ALTER TABLE contract_lifecycle_commands ENABLE TRIGGER USER")
    with pytest.raises(SessionRestoreError, match="restore_contract_lifecycle_invalid"):
        with postgres.engine.begin() as db:
            invalidate_and_inspect(db, {"JWT_SECRET_KEY": "synthetic-offline-signing-secret"}, deadline=time.monotonic() + 30)
    with postgres.engine.connect() as db:
        assert db.scalar(select(AuthSessionORM.revoked_at).where(AuthSessionORM.id == family)) is None


def test_actual_postgresql_reset_refuses_before_destructive_dml(postgres):
    from backend.tests.test_contract_lifecycle_application import (
        test_known_history_reset_refuses_before_any_dml_and_preserves_memory_clone,
    )
    test_known_history_reset_refuses_before_any_dml_and_preserves_memory_clone(postgres)
