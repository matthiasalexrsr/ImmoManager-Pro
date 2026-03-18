"""Entity photo management and file upload router."""

import logging
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from ..dependencies import store
from ..models import EntityPhoto, EntityPhotoCreate, EntityPhotoPatch
from ..services.file_storage import get_file_storage
from ..storage import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/photos", tags=["Fotos"])


@router.get("", response_model=list[EntityPhoto])
def list_photos(
    entity_type: str = Query(..., description="property or unit"),
    entity_id: str = Query(...),
) -> list[EntityPhoto]:
    return store.list_entity_photos(entity_type, entity_id)


@router.post("/upload", response_model=EntityPhoto, status_code=status.HTTP_201_CREATED)
async def upload_photo(
    entity_type: str = Query(..., description="property or unit"),
    entity_id: str = Query(...),
    caption: str = Query(""),
    is_primary: bool = Query(False),
    file: UploadFile = File(...),
) -> EntityPhoto:
    """Upload a photo file and create an EntityPhoto record."""
    storage = get_file_storage()
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    key = f"photos/{entity_type}/{entity_id}/{uuid.uuid4().hex}.{ext}"
    storage.save(key, file.file, content_type=file.content_type or "image/jpeg")
    file_url = storage.get_url(key)

    data = EntityPhotoCreate(
        entity_type=entity_type,
        entity_id=entity_id,
        file_url=file_url,
        caption=caption,
        is_primary=is_primary,
    )
    return store.create_entity_photo(data)


@router.patch("/{photo_id}", response_model=EntityPhoto)
def patch_photo(photo_id: str, payload: EntityPhotoPatch) -> EntityPhoto:
    try:
        return store._patch_entity("entity_photo", photo_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: str) -> None:
    try:
        photo = store.get_entity_photo(photo_id)
        # Try to delete the file too
        try:
            storage = get_file_storage()
            key = photo.file_url.replace("/uploads/", "")
            storage.delete(key)
        except Exception:
            logger.warning("Failed to delete photo file: %s", photo.file_url)
        store.delete_entity_photo(photo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
