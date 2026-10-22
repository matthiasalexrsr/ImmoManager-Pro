"""Budget planning router (T27)."""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..dependencies import store
from ..domain.money import as_number, money, money_sum
from ..models import Budget, BudgetCreate, BudgetPatch
from ..services import budget_actuals
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
    budget_actuals.validate_categories(store, payload)
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
    total_planned = money_sum(b.planned_amount for b in results)
    total_actual = money_sum(b.actual_amount for b in results)

    def utilization(actual: Decimal, planned: Decimal) -> float:
        return float(actual / planned * 100) if planned else 0

    return {
        "total_planned": as_number(total_planned),
        "total_actual": as_number(total_actual),
        "total_deviation": as_number(total_actual - total_planned),
        "utilization_percent": utilization(total_actual, total_planned),
        "by_category": [
            {
                "id": b.id,
                "category": b.category,
                "planned": as_number(money(b.planned_amount)),
                "actual": as_number(money(b.actual_amount)),
                "deviation": as_number(money(b.actual_amount) - money(b.planned_amount)),
                "utilization_percent": utilization(money(b.actual_amount), money(b.planned_amount)),
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


def _budget(budget_id: str) -> Budget:
    try:
        return store.get_budget(budget_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{budget_id}/actual-from-bookings", response_model=None)
def actual_from_bookings(budget_id: str):
    """What the bookings of the chosen categories spent in the budget's year (nothing is saved)."""
    return budget_actuals.from_bookings(store, _budget(budget_id))


class TakeActual(BaseModel):
    expected_amount: float | None = None  # the amount the user saw


@router.post("/{budget_id}/actual-from-bookings", response_model=Budget)
def take_actual_from_bookings(budget_id: str, payload: TakeActual):
    """Save the amount from the bookings as the budget's actual amount."""
    expected = None if payload.expected_amount is None else Decimal(str(payload.expected_amount))
    return budget_actuals.apply(store, _budget(budget_id), expected)


@router.put("/{budget_id}", response_model=Budget)
def update_budget(budget_id: str, payload: BudgetCreate):
    budget_actuals.validate_categories(store, payload)
    try:
        return store.update_budget(budget_id, payload)
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.patch("/{budget_id}", response_model=Budget)
def patch_budget(budget_id: str, payload: BudgetPatch):
    try:
        current = store.get_budget(budget_id)
        merged = {**current.model_dump(include=set(BudgetCreate.model_fields)), **payload.model_dump(exclude_unset=True)}
        budget_actuals.validate_categories(store, BudgetCreate(**merged))
        return store._patch_entity("budget", budget_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: str):
    try:
        store.delete_budget(budget_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
