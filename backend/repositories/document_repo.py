"""Document domain repository — documents, entity photos."""

import logging

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..db.orm_models import ContractORM, DocumentORM, EntityPhotoORM
from ..models import (
    Document,
    DocumentCreate,
    EntityPhoto,
    EntityPhotoCreate,
)
from ..storage import ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


def _document_search_text(column):
    """SQLite's lower() folds ASCII only; fold German characters in SQL too."""
    for uppercase, folded in (("Ä", "ä"), ("Ö", "ö"), ("Ü", "ü"), ("ẞ", "ss"), ("ß", "ss")):
        column = func.replace(column, uppercase, folded)
    return func.lower(column)


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

    def validate_document_associations(self, data: DocumentCreate) -> None:
        pr = self._portfolio_repo
        tr = self._tenant_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id and tr and not tr._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        if data.unit_id and data.property_id and pr:
            if pr._units.get(data.unit_id).property_id != data.property_id:
                raise ValidationError("Einheit gehört nicht zur Immobilie")
        if data.contract_id and tr:
            if not tr._contracts.exists(data.contract_id):
                raise ValidationError("Vertrag existiert nicht")
            contract = tr._contracts.get(data.contract_id)
            if data.tenant_id and contract.tenant_id != data.tenant_id:
                raise ValidationError("Vertrag gehört nicht zum Mieter")
            if data.property_id and contract.property_id != data.property_id:
                raise ValidationError("Vertrag gehört nicht zur Immobilie")
            if data.unit_id and contract.unit_id != data.unit_id:
                raise ValidationError("Vertrag gehört nicht zur Einheit")

    def create_document(self, data: DocumentCreate) -> Document:
        self.validate_document_associations(data)
        result = self._documents.create(data)
        self._commit()
        return result

    def get_document(self, document_id: str) -> Document:
        return self._documents.get(document_id)

    def update_document(self, document_id: str, data: DocumentCreate) -> Document:
        self._documents.get(document_id)
        self.validate_document_associations(data)
        result = self._documents.update(document_id, data)
        self._commit()
        return result

    def delete_document(self, document_id: str) -> None:
        self._documents.delete(document_id)
        self._commit()

    def _tenant_document_query(self, tenant_id: str):
        """An explicit tenant owns the document even if its contract is reassigned later."""
        contract_ids = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
        return self.db.query(DocumentORM).filter(or_(
            DocumentORM.tenant_id == tenant_id,
            and_(DocumentORM.tenant_id.is_(None), DocumentORM.contract_id.in_(contract_ids)),
        ))

    def tenant_document_summary(self, tenant_id: str) -> dict:
        query = self._tenant_document_query(tenant_id)
        types = query.with_entities(DocumentORM.document_type).filter(
            DocumentORM.document_type.isnot(None), DocumentORM.document_type != "",
        ).distinct().order_by(DocumentORM.document_type).all()
        return {"document_count": query.count(), "document_types": [row[0] for row in types]}

    def list_tenant_documents(
        self, tenant_id: str, skip: int = 0, limit: int = 25, q: str | None = None,
        document_type: str | None = None, contract_id: str | None = None,
    ) -> dict:
        if contract_id:
            contract = self.db.get(ContractORM, contract_id)
            if contract is None or contract.tenant_id != tenant_id:
                raise ValidationError("Vertrag gehört nicht zum Mieter")
        query = self._tenant_document_query(tenant_id)
        if contract_id:
            query = query.filter(DocumentORM.contract_id == contract_id)
        if document_type:
            query = query.filter(DocumentORM.document_type == document_type)
        search = (q or "").strip().casefold()
        if search:
            # contains(autoescape=True) treats %, _ and / as literal search text.
            query = query.filter(or_(*(
                _document_search_text(getattr(DocumentORM, field)).contains(search, autoescape=True)
                for field in ("title", "document_type", "tags", "description")
            )))
        total = query.count()
        items = self._documents._read(query.order_by(
            DocumentORM.created_at.desc(), DocumentORM.id.desc(),
        ).offset(skip).limit(limit))
        return {"items": items, "total": total, "skip": skip, "limit": limit,
                "has_more": skip + limit < total}

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
