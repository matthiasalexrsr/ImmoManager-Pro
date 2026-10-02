"""The production restore probe must read SQL users in its fresh helper process."""

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.orm_models import Base
from scripts.private_server_smoke import LEGACY_PAIR


def test_restore_smoke_legacy_pair_uses_persisted_users_in_fresh_process(tmp_path, monkeypatch):
    database_url = "sqlite:///" + (tmp_path / "source-auth.sqlite").as_posix()
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    try:
        password = "Synthetic-restore-password-2026!"
        viewer = auth.register_user("viewer0", "viewer0@example.invalid", "Synthetic viewer", password, "readonly")
        environment = {**os.environ, "DATABASE_URL": database_url,
            "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false",
            "ENVIRONMENT": "development", "JWT_SECRET_KEY": auth.SECRET_KEY}
        result = subprocess.run([sys.executable, "-c", LEGACY_PAIR],
            input=json.dumps({"password": password}), text=True, capture_output=True,
            cwd=Path(__file__).resolve().parents[2], env=environment, timeout=30)
        assert result.returncode == 0, result.stderr
        pair = json.loads(result.stdout)
        assert set(pair) == {"access_token", "refresh_token"}
        assert auth.decode_token(pair["access_token"]).sub == viewer.id
        assert auth.decode_token(pair["refresh_token"]).sub == viewer.id
        assert auth.decode_token(pair["access_token"]).sid is None
    finally:
        engine.dispose()
