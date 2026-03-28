"""Portfolio domain repository — portfolios, properties, units, accounts, categories."""

import logging
from sqlalchemy.orm import Session

from ..db.orm_models import (
    AccountORM, CategoryORM, PortfolioORM, PropertyORM, UnitORM,
)
from ..models import (
    Account, AccountCreate,
    Category, CategoryCreate,
    Portfolio, PortfolioCreate,
    Property, PropertyCreate,
    Unit, UnitCreate,
)
from ..storage import NotFoundError, ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class PortfolioRepository:
    """Portfolios, properties, units, accounts, and categories."""

    def __init__(self, db: Session):
        self.db = db
        self._portfolios = BaseRepository(db, PortfolioORM, Portfolio, "Portfolio nicht gefunden")
        self._properties = BaseRepository(db, PropertyORM, Property, "Immobilie nicht gefunden")
        self._units = BaseRepository(db, UnitORM, Unit, "Einheit nicht gefunden")
        self._accounts = BaseRepository(db, AccountORM, Account, "Konto nicht gefunden")
        self._categories = BaseRepository(db, CategoryORM, Category, "Kategorie nicht gefunden")

    def _commit(self):
        self.db.commit()

    # --- Portfolios ---
    def list_portfolios(self) -> list[Portfolio]:
        return self._portfolios.list_all()

    def create_portfolio(self, data: PortfolioCreate) -> Portfolio:
        result = self._portfolios.create(data)
        self._commit()
        return result

    def get_portfolio(self, portfolio_id: str) -> Portfolio:
        return self._portfolios.get(portfolio_id)

    def update_portfolio(self, portfolio_id: str, data: PortfolioCreate) -> Portfolio:
        result = self._portfolios.update(portfolio_id, data)
        self._commit()
        return result

    def delete_portfolio(self, portfolio_id: str) -> None:
        self._portfolios.delete(portfolio_id)
        self._commit()

    # --- Accounts ---
    def list_accounts(self) -> list[Account]:
        return self._accounts.list_all()

    def create_account(self, data: AccountCreate) -> Account:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._accounts.create(data)
        self._commit()
        return result

    def get_account(self, account_id: str) -> Account:
        return self._accounts.get(account_id)

    def update_account(self, account_id: str, data: AccountCreate) -> Account:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._accounts.update(account_id, data)
        self._commit()
        return result

    def delete_account(self, account_id: str) -> None:
        self._accounts.delete(account_id)
        self._commit()

    # --- Categories ---
    def list_categories(self) -> list[Category]:
        return self._categories.list_all()

    def create_category(self, data: CategoryCreate) -> Category:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._categories.create(data)
        self._commit()
        return result

    def get_category(self, category_id: str) -> Category:
        return self._categories.get(category_id)

    def update_category(self, category_id: str, data: CategoryCreate) -> Category:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._categories.update(category_id, data)
        self._commit()
        return result

    def delete_category(self, category_id: str) -> None:
        self._categories.delete(category_id)
        self._commit()

    # --- Properties ---
    def list_properties(self) -> list[Property]:
        return self._properties.list_all()

    def create_property(self, data: PropertyCreate) -> Property:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._properties.create(data)
        self._commit()
        return result

    def get_property(self, property_id: str) -> Property:
        return self._properties.get(property_id)

    def update_property(self, property_id: str, data: PropertyCreate) -> Property:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._properties.update(property_id, data)
        self._commit()
        return result

    def delete_property(self, property_id: str) -> None:
        self._properties.delete(property_id)
        self._commit()

    # --- Units ---
    def list_units(self) -> list[Unit]:
        return self._units.list_all()

    def create_unit(self, data: UnitCreate) -> Unit:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._units.create(data)
        self._commit()
        return result

    def get_unit(self, unit_id: str) -> Unit:
        return self._units.get(unit_id)

    def update_unit(self, unit_id: str, data: UnitCreate) -> Unit:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._units.update(unit_id, data)
        self._commit()
        return result

    def delete_unit(self, unit_id: str) -> None:
        self._units.delete(unit_id)
        self._commit()
