"""Document domain repository — documents, entity photos."""

import logging

from sqlalchemy.orm import Session

from ..db.orm_models import DocumentORM, EntityPhotoORM
from ..models import (
    Document,
    DocumentCreate,
    EntityPhoto,
    EntityPhotoCreate,
)
from ..storage import ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Documents and entity photos."""

    def __init__(self, db: Session, portfolio_repo=None, tenant_repo=None):
        self.db = db
        self._documents = BaseRepository(db, DocumentORM, Document, "Dokument nicht gefunden")
        self._entity_photos = BaseRepository(db, EntityPhotoORM, EntityPhoto, "Foto nicht gefunden")
        self._portfolio_repo = portfolio_repo
        self._tenant_repo = tenant_repo

    def _commit(self):
        self.db.commit()

    # --- Documents ---
    def list_documents(self) -> list[Document]:
        return self._documents.list_all()

    def create_document(self, data: DocumentCreate) -> Document:
        pr = self._portfolio_repo
        tr = self._tenant_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.contract_id and tr and not tr._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._documents.create(data)
        self._commit()
        return result

    def get_document(self, document_id: str) -> Document:
        return self._documents.get(document_id)

    def update_document(self, document_id: str, data: DocumentCreate) -> Document:
        pr = self._portfolio_repo
        tr = self._tenant_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.contract_id and tr and not tr._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._documents.update(document_id, data)
        self._commit()
        return result

    def delete_document(self, document_id: str) -> None:
        self._documents.delete(document_id)
        self._commit()

    # --- Entity Photos ---
    def list_entity_photos(self, entity_type: str, entity_id: str) -> list[EntityPhoto]:
        return self._entity_photos.filter_by(entity_type=entity_type, entity_id=entity_id)

    def create_entity_photo(self, data: EntityPhotoCreate) -> EntityPhoto:
        result = self._entity_photos.create(data)
        self._commit()
        return result

    def get_entity_photo(self, photo_id: str) -> EntityPhoto:
        return self._entity_photos.get(photo_id)

    def delete_entity_photo(self, photo_id: str) -> None:
        self._entity_photos.delete(photo_id)
        self._commit()
