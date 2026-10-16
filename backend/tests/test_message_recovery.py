"""A complete archive retains message identity, receipt, grants, keys and attachment bytes."""

import hashlib
import json
from uuid import uuid4

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db import schema_state
from backend.models import DocumentCreate, MessageThreadCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import full_backup
from backend.services.full_backup import Sources
from backend.services.message_threads import MessageSubmission, message_page, send_message
from backend.services.secret_box import SecretBox


def test_full_archive_restores_internal_reply_without_duplicate_after_lost_success(tmp_path, monkeypatch):
    data = tmp_path / "original-installation"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    original = b"Synthetic immutable attachment evidence\x00\x01\xff" * 100
    (uploads / "original.bin").write_bytes(original)
    database = data / "immo_manager.db"
    engine = create_engine(f"sqlite:///{database}")
    restored_engine = None
    try:
        schema_state.initialise_empty(engine)
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(bind=engine)))
        owner = auth.register_user("recovery-owner", "recovery@example.test", "Wiederherstellung", "Secret123", "eigentuemer")
        with Session(engine) as db:
            source = SQLAlchemyStore(db)
            portfolio = source.create_portfolio(PortfolioCreate(name="Archivbestand"))
            prop = source.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Archivhaus", property_type="residential"))
            document = source.create_document(DocumentCreate(title="Originalbeleg", document_type="other",
                                                              property_id=prop.id, file_url="/uploads/original.bin"))
            thread = source.create_message_thread(MessageThreadCreate(subject="Nachvollziehbarer Vorgang", property_id=prop.id))
            command = MessageSubmission(thread_id=thread.id, body="Diese Nachricht darf nur einmal entstehen.",
                                        attachment_ids=document.id, idempotency_key=str(uuid4()),
                                        base_revision=thread.updated_at.isoformat())
            saved = send_message(source, thread.id, command, owner.id)
            assert message_page(source, thread.id, owner.id)["total"] == 1
        box = SecretBox(data / "secrets" / "keyring.json")
        sealed = box.seal("synthetic recoverable evidence", "integrations/qa-extension/proof")
        state = data / "integrations.json"
        state.write_text(json.dumps({"enabled": {}, "config": {"qa-extension": {"proof": sealed}}}), encoding="utf-8")
        (data / ".env").write_text("JOB_SCHEDULER_ENABLED=false\nBACKUP_SCHEDULE_ENABLED=false\n", encoding="utf-8")
        sources = Sources(database_url=f"sqlite:///{database}", data_dir=data, uploads_dir=uploads,
                          root=data / "backups" / "full", integration_state=state, key_file=box.key_file,
                          env_file=data / ".env")
        archive = full_backup.create_full_backup("manual", sources)
        assert archive["ok"]
        archive_path = sources.root / archive["archive"]
        assert full_backup.verify_archive(archive_path, expected_sha256=archive["sha256"])["ok"]
        target = tmp_path / "restored-installation"
        report = full_backup.restore_archive(archive_path, target)
        assert report["revision"] == schema_state.head_revision()
        assert (target / "uploads" / "original.bin").read_bytes() == original
        assert hashlib.sha256((target / "uploads" / "original.bin").read_bytes()).digest() == hashlib.sha256(original).digest()
        recovered_box = SecretBox(target / "secrets" / "keyring.json")
        recovered_state = json.loads((target / "integrations.json").read_text(encoding="utf-8"))
        assert recovered_box.open(recovered_state["config"]["qa-extension"]["proof"], "integrations/qa-extension/proof") == "synthetic recoverable evidence"
        # Remove the original location before re-opening the restored database.
        # The caller cannot accidentally pass this proof using its original DB.
        engine.dispose()
        data.rename(tmp_path / "original-no-longer-available")
        assert not database.exists()
        restored_database = target / "immo_manager.db"
        assert restored_database.is_file()
        restored_engine = create_engine(f"sqlite:///{restored_database}")
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(bind=restored_engine)))
        account = auth.authenticate_user("recovery-owner", "Secret123")
        assert account is not None and account["id"] == owner.id
        with Session(restored_engine) as db:
            recovered = SQLAlchemyStore(db)
            replay = send_message(recovered, thread.id, command, owner.id)
            assert replay == saved
            page = message_page(recovered, thread.id, owner.id)
            assert page["total"] == 1 and page["items"] == [saved]
            assert recovered.get_message_thread(thread.id).message_count == 1
            assert recovered.get_document(document.id).file_url == "/uploads/original.bin"
            assert any(index["name"] == "ix_messages_thread_sent_id" for index in inspect(restored_engine).get_indexes("messages"))
    finally:
        engine.dispose()
        if restored_engine is not None:
            restored_engine.dispose()
