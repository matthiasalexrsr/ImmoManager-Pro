from fastapi import APIRouter, HTTPException, status

from ..models import Listing, ListingCreate, ListingPhoto, ListingPhotoCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/listings", tags=["Inserate"])


@router.get("", response_model=list[Listing])
def list_listings() -> list[Listing]:
    return store.list_listings()


@router.post("", response_model=Listing, status_code=status.HTTP_201_CREATED)
def create_listing(payload: ListingCreate) -> Listing:
    try:
        return store.create_listing(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing(listing_id: str) -> None:
    try:
        store.delete_listing(listing_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/photos", response_model=list[ListingPhoto])
def list_listing_photos() -> list[ListingPhoto]:
    return store.list_listing_photos()


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


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing_photo(photo_id: str) -> None:
    try:
        store.delete_listing_photo(photo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
