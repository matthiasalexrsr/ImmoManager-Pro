"""Account writes preserve IBAN uniqueness across ciphertext key versions."""

from ..db.orm_models import AccountORM
from ..error_helpers import safe_db_operation
from ..services.iban_encryption import IBANEncryptionError, current_keyring
from ..services.iban_schema import guard_account_write
from .base import BaseRepository, _generate_id


class AccountRepository(BaseRepository):
    def _prepared(self, updates):
        ring = current_keyring()
        guard_account_write(self.db.connection(), ring)
        if "iban" in updates:
            updates = {**updates, "iban_fingerprint": ring.fingerprint(updates["iban"])}
        return updates

    @safe_db_operation("create_account")
    def create(self, data):
        try:
            values = self._prepared(data.model_dump())
            obj = AccountORM(id=_generate_id(), **values)
            self.db.add(obj)
            self.db.flush()
            self.db.refresh(obj)
            return self._to_pydantic(obj)
        except IBANEncryptionError:
            self.db.rollback()
            raise

    def _write(self, entity_id, updates):
        try:
            return super()._write(entity_id, self._prepared(updates))
        except IBANEncryptionError:
            self.db.rollback()
            raise
