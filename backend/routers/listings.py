from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Listing, ListingCreate, ListingPatch, ListingPhoto, ListingPhotoCreate, ListingPhotoPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/listings", tags=["Inserate"])


@router.get("", response_model=list[Listing])
def list_listings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    unit_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
) -> list[Listing]:
    results = store.list_listings()
    if unit_id:
        results = [lst for lst in results if lst.unit_id == unit_id]
    if status_filter:
        results = [lst for lst in results if lst.status == status_filter]
    return results[skip : skip + limit]


@router.post("", response_model=Listing, status_code=status.HTTP_201_CREATED)
def create_listing(payload: ListingCreate) -> Listing:
    try:
        return store.create_listing(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# --- Photo sub-routes MUST be registered before /{listing_id} ---


@router.get("/photos", response_model=list[ListingPhoto])
def list_listing_photos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    listing_id: str | None = Query(None),
) -> list[ListingPhoto]:
    results = store.list_listing_photos()
    if listing_id:
        results = [p for p in results if p.listing_id == listing_id]
    return results[skip : skip + limit]


@router.post("/photos", response_model=ListingPhoto, status_code=status.HTTP_201_CREATED)
def create_listing_photo(payload: ListingPhotoCreate) -> ListingPhoto:
    try:
        return store.create_listing_photo(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/photos/{photo_id}", response_model=ListingPhoto)
def get_listing_photo(photo_id: str) -> ListingPhoto:
    try:
        return store.get_listing_photo(photo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/photos/{photo_id}", response_model=ListingPhoto)
def update_listing_photo(photo_id: str, payload: ListingPhotoCreate) -> ListingPhoto:
    try:
        return store.update_listing_photo(photo_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/photos/{photo_id}", response_model=ListingPhoto)
def patch_listing_photo(photo_id: str, payload: ListingPhotoPatch) -> ListingPhoto:
    try:
        return store._patch_entity("listing_photo", photo_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing_photo(photo_id: str) -> None:
    try:
        store.delete_listing_photo(photo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- Listing detail routes (after /photos to avoid path conflicts) ---


@router.get("/{listing_id}", response_model=Listing)
def get_listing(listing_id: str) -> Listing:
    try:
        return store.get_listing(listing_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{listing_id}", response_model=Listing)
def update_listing(listing_id: str, payload: ListingCreate) -> Listing:
    try:
        return store.update_listing(listing_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{listing_id}", response_model=Listing)
def patch_listing(listing_id: str, payload: ListingPatch) -> Listing:
    try:
        return store._patch_entity("listing", listing_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing(listing_id: str) -> None:
    try:
        store.delete_listing(listing_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
