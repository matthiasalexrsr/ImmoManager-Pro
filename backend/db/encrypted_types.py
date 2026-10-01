"""Account IBAN binds/results are encrypted transparently at the SQL boundary."""

from sqlalchemy import Text, event, inspect
from sqlalchemy.exc import DontWrapMixin
from sqlalchemy.types import TypeDecorator

from ..services.iban_encryption import IBANEncryptionError, current_keyring, decrypt_iban, encrypt_iban


class SQLIBANEncryptionError(IBANEncryptionError, DontWrapMixin):
    """Prevent SQLAlchemy from attaching parameters to a failed IBAN bind."""


class EncryptedIBAN(TypeDecorator[str]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        try:
            return encrypt_iban(value) if value and value.strip() else None
        except IBANEncryptionError as error:
            raise SQLIBANEncryptionError(error.code) from None

    def process_result_value(self, value, dialect):
        return decrypt_iban(value)


def register_account_encryption(account_class):
    """Native ORM writes also maintain the index; unrelated balance writes do not migrate legacy fields."""

    def before_write(mapper, connection, account):
        if inspect(account).attrs.iban.history.has_changes():
            from ..services.iban_schema import guard_account_write

            ring = current_keyring()
            guard_account_write(connection, ring)
            account.iban_fingerprint = ring.fingerprint(account.iban)

    event.listen(account_class, "before_insert", before_write)
    event.listen(account_class, "before_update", before_write)
