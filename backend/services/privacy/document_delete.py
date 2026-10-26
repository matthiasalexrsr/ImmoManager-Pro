"""Delete an unarchived document and retain its privacy tombstone atomically."""
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import text

from ...db.privacy_models import PrivacyControlORM
from .. import document_retention, document_text
from .. import document_versions as archive
from ..data_transfer.common import digest
from ..integrations import connection_storage as db
from ..maintenance_rows import Rows
from ..portfolio_scope import scope_context, scope_from_user
from ..private_dependencies import ensure_unbound
from .storage import control, key, receipt


def remove(store, actor_id, identifier, override_reason=None):
    with archive.work(store, actor_id, write_areas=("/documents",)) as unit:
        with scope_context(scope_from_user(unit.user)):
            if unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                unit.db.execute(text("SELECT pg_advisory_xact_lock(725627501)"))
            source = Rows.of(unit)
            source.lock("documents", identifier)
            document = source.require("documents", identifier, "Dokument nicht gefunden.")
            archive.ensure_no_originals(unit.store, "document", identifier)
            ensure_unbound(unit.store, "documents", identifier)
            assessment = document_retention.ensure_deletable(unit.store, identifier, actor=unit.user, override_reason=override_reason)
            if assessment.get("override"):
                document_retention.record_override(unit.store, unit.user, document, assessment)
            old = control(unit, "document", identifier)
            sha = digest(document.model_dump(mode="json"))
            reason = override_reason or "Dokumentlöschung nach Prüfung der Aufbewahrung und fachlichen Zuordnungen."
            source.delete("documents", identifier)
            if unit.db is None and identifier in document_text.memory_rows(unit.store):
                unit.remove(document_text.memory_rows(unit.store), identifier)
            db.put(unit, PrivacyControlORM, {"id": key("document", identifier), "kind": "document", "record_id": identifier,
                "held": False, "restricted": True, "erased_at": db.now(), "erasure_due": False, "revision": (old.revision if old else 0) + 1,
                "reason": reason, "actor_id": unit.actor_id, "source_sha256": sha, "created_at": old.created_at if old else db.now(), "updated_at": db.now()})
            command = SimpleNamespace(reason=reason, idempotency_key=uuid4().hex,
                model_dump=lambda **_: {"document_id": identifier, "sha256": sha, "reason": reason})
            receipt(unit, "erase", "document", identifier, command, sha,
                {"removed": "Dokumentdatensatz und Suchindex", "retained": "Dateispeicher und Sicherungskopien sind getrennt auf verbleibende Dateikopien zu prüfen."})
