"""Explicit preservation guards for Root's reset/transfer/account hooks."""
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from ..db.bank_import_models import BankImportORM
from ..db.orm_models import AccountORM
from .bank_import import BankImportError
from .portfolio_scope import scope_context


def _has_history(store, account_id=None):
    engine = getattr(store, "_bank_import_engine", None)
    if not hasattr(store, "db") and engine is None:
        return False
    with scope_context(None):
        if hasattr(store, "db"):
            db = store.db
            if not inspect(db.get_bind()).has_table("bank_imports"):
                return False
            statement = select(BankImportORM.id)
            if account_id:
                statement = statement.where(BankImportORM.account_id == account_id)
            return db.scalar(statement.limit(1)) is not None
        with Session(engine) as db:
            statement = select(BankImportORM.id)
            if account_id:
                statement = statement.where(BankImportORM.account_id == account_id)
            return db.scalar(statement.limit(1)) is not None


def guard_bank_import_reset(store):
    """Call before destructive user-requested reset/subset replacement."""
    if _has_history(store):
        raise BankImportError("BANK_IMPORT_HISTORY_PRESENT",
            "Bankdateien und geprüfte Importherkunft würden verloren gehen. Bestand erhalten oder vollständige Recovery-Sicherung verwenden.",
            409, "preserve_history_or_full_recovery")


def guard_bank_import_business_transfer(store, *, operation, memory_journal_preserved=False):
    """Business JSON cannot carry original bytes or deepcopy a Memory engine."""
    if operation == "merge":
        # Additive SQL merge publishes new business IDs and never replaces its
        # original journal/account bindings. Memory requires Root's explicit
        # deepcopy memo + RLock protocol to retain the same journal engine.
        if hasattr(store, "db") or memory_journal_preserved:
            return
        if getattr(store, "_bank_import_engine", None) is not None:
            raise BankImportError("BANK_MEMORY_JOURNAL_SEPARATE",
                "Memory-Importjournal muss bei der Zusammenführung erhalten bleiben. Eine ausdrücklich journalerhaltende Zusammenführung verwenden.",
                409, "preserve_memory_journal")
    if _has_history(store):
        raise BankImportError("BANK_IMPORT_HISTORY_PRESENT",
            "Geschäfts-JSON enthält keine gesicherten Bankdateien und keine Importherkunft. Bestehendes Journal erhalten oder vollständige Recovery-Sicherung verwenden.",
            409, "preserve_history_or_full_recovery")


def guard_bank_import_account_delete(store, account_id):
    """Call after ordinary scope lookup, before FK deletion of an account."""
    if _has_history(store, account_id):
        raise BankImportError("BANK_ACCOUNT_IMPORT_HISTORY",
            "Konto besitzt gesicherte Bankdateien oder Importherkunft und kann nicht gelöscht werden. Konto und Historie erhalten; vollständige Sicherung vor Bestandsänderung erstellen.",
            409, "preserve_account_and_history")


def guard_bank_import_portfolio_delete(store, portfolio_id):
    """Current parent binding protects SQL cascades and Memory internal deletes."""
    engine = getattr(store, "_bank_import_engine", None)
    if not hasattr(store, "db") and engine is None:
        return
    present = False
    with scope_context(None):
        if hasattr(store, "db"):
            db = store.db
            if not inspect(db.get_bind()).has_table("bank_imports"):
                return
            present = db.scalar(select(BankImportORM.id).join(AccountORM, AccountORM.id == BankImportORM.account_id)
                .where(AccountORM.portfolio_id == portfolio_id).limit(1)) is not None
        else:
            with Session(engine) as db:
                after = ""
                while True:
                    identifiers = list(db.scalars(select(BankImportORM.account_id).where(BankImportORM.account_id > after)
                        .distinct().order_by(BankImportORM.account_id).limit(100)))
                    if not identifiers:
                        break
                    for identifier in identifiers:
                        account = store.accounts.get(identifier)
                        if account and account.portfolio_id == portfolio_id:
                            present = True
                            break
                    if present:
                        break
                    after = identifiers[-1]
    if present:
        raise BankImportError("BANK_PORTFOLIO_IMPORT_HISTORY",
            "Portfolio enthält Konten mit gesicherten Bankdateien oder Importherkunft. Portfolio, Konten und Historie erhalten; vollständige Sicherung vor Bestandsänderung erstellen.",
            409, "preserve_portfolio_and_history")
