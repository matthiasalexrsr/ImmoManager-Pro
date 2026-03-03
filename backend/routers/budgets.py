"""Budget planning router (T27)."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Budget, BudgetCreate, BudgetPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/budgets", tags=["Budgetplanung"])


@router.get("", response_model=list[Budget])
def list_budgets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    year: int | None = Query(None),
    category: str | None = Query(None),
):
    results = store.list_budgets()
    if property_id:
        results = [b for b in results if b.property_id == property_id]
    if year:
        results = [b for b in results if b.year == year]
    if category:
        results = [b for b in results if b.category == category]
    return results[skip: skip + limit]


@router.post("", response_model=Budget, status_code=status.HTTP_201_CREATED)
def create_budget(payload: BudgetCreate):
    try:
        return store.create_budget(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analysis", response_model=None)
def budget_analysis(
    property_id: str | None = Query(None),
    year: int | None = Query(None),
):
    """Budget vs. actual analysis with deviation."""
    results = store.list_budgets()
    if property_id:
        results = [b for b in results if b.property_id == property_id]
    if year:
        results = [b for b in results if b.year == year]
    total_planned = sum(b.planned_amount for b in results)
    total_actual = sum(b.actual_amount for b in results)
    return {
        "total_planned": total_planned,
        "total_actual": total_actual,
        "total_deviation": total_actual - total_planned,
        "utilization_percent": (total_actual / total_planned * 100) if total_planned else 0,
        "by_category": [
            {
                "id": b.id,
                "category": b.category,
                "planned": b.planned_amount,
                "actual": b.actual_amount,
                "deviation": b.actual_amount - b.planned_amount,
                "utilization_percent": (b.actual_amount / b.planned_amount * 100) if b.planned_amount else 0,
            }
            for b in results
        ],
    }


@router.get("/{budget_id}", response_model=Budget)
def get_budget(budget_id: str):
    try:
        return store.get_budget(budget_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{budget_id}", response_model=Budget)
def update_budget(budget_id: str, payload: BudgetCreate):
    try:
        return store.update_budget(budget_id, payload)
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.patch("/{budget_id}", response_model=Budget)
def patch_budget(budget_id: str, payload: BudgetPatch):
    try:
        return store._patch_entity(None, budget_id, payload, "Budget nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: str):
    try:
        store.delete_budget(budget_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
