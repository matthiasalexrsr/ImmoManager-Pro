"""Marketing domain repository — listings, listing photos."""

import logging
from sqlalchemy.orm import Session

from ..db.orm_models import ListingORM, ListingPhotoORM
from ..models import (
    Listing, ListingCreate,
    ListingPhoto, ListingPhotoCreate,
)
from ..storage import ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class MarketingRepository:
    """Listings and listing photos."""

    def __init__(self, db: Session, portfolio_repo=None):
        self.db = db
        self._listings = BaseRepository(db, ListingORM, Listing, "Inserat nicht gefunden")
        self._listing_photos = BaseRepository(db, ListingPhotoORM, ListingPhoto, "Inseratsfoto nicht gefunden")
        self._portfolio_repo = portfolio_repo

    def _commit(self):
        self.db.commit()

    # --- Listings ---
    def list_listings(self) -> list[Listing]:
        return self._listings.list_all()

    def create_listing(self, data: ListingCreate) -> Listing:
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._listings.create(data)
        self._commit()
        return result

    def get_listing(self, listing_id: str) -> Listing:
        return self._listings.get(listing_id)

    def update_listing(self, listing_id: str, data: ListingCreate) -> Listing:
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._listings.update(listing_id, data)
        self._commit()
        return result

    def delete_listing(self, listing_id: str) -> None:
        self._listings.delete(listing_id)
        self._commit()

    # --- Listing Photos ---
    def list_listing_photos(self) -> list[ListingPhoto]:
        return self._listing_photos.list_all()

    def create_listing_photo(self, data: ListingPhotoCreate) -> ListingPhoto:
        if not self._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        result = self._listing_photos.create(data)
        self._commit()
        return result

    def get_listing_photo(self, photo_id: str) -> ListingPhoto:
        return self._listing_photos.get(photo_id)

    def update_listing_photo(self, photo_id: str, data: ListingPhotoCreate) -> ListingPhoto:
        if not self._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        result = self._listing_photos.update(photo_id, data)
        self._commit()
        return result

    def delete_listing_photo(self, photo_id: str) -> None:
        self._listing_photos.delete(photo_id)
        self._commit()
