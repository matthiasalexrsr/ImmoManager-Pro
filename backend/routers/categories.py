from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Category, CategoryCreate, CategoryPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/categories", tags=["Kategorien"])


@router.get("", response_model=list[Category])
def list_categories(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    portfolio_id: str | None = Query(None),
    category_type: str | None = Query(None),
) -> list[Category]:
    results = store.list_categories()
    if portfolio_id:
        results = [c for c in results if c.portfolio_id == portfolio_id]
    if category_type:
        results = [c for c in results if c.category_type == category_type]
    return results[skip : skip + limit]


@router.post("", response_model=Category, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate) -> Category:
    try:
        return store.create_category(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{category_id}", response_model=Category)
def get_category(category_id: str) -> Category:
    try:
        return store.get_category(category_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{category_id}", response_model=Category)
def update_category(category_id: str, payload: CategoryCreate) -> Category:
    try:
        return store.update_category(category_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{category_id}", response_model=Category)
def patch_category(category_id: str, payload: CategoryPatch) -> Category:
    try:
        return store._patch_entity(store.categories, category_id, payload, "Kategorie nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: str) -> None:
    try:
        store.delete_category(category_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
