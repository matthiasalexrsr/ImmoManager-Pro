from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Portfolio, PortfolioCreate, PortfolioPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/portfolios", tags=["Portfolios"])


@router.get("", response_model=list[Portfolio])
def list_portfolios(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: str | None = Query(None, alias="status"),
) -> list[Portfolio]:
    results = store.list_portfolios()
    if status_filter:
        results = [p for p in results if p.status == status_filter]
    return results[skip : skip + limit]


@router.post("", response_model=Portfolio, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: PortfolioCreate) -> Portfolio:
    try:
        return store.create_portfolio(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{portfolio_id}", response_model=Portfolio)
def get_portfolio(portfolio_id: str) -> Portfolio:
    try:
        return store.get_portfolio(portfolio_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{portfolio_id}", response_model=Portfolio)
def update_portfolio(portfolio_id: str, payload: PortfolioCreate) -> Portfolio:
    try:
        return store.update_portfolio(portfolio_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{portfolio_id}", response_model=Portfolio)
def patch_portfolio(portfolio_id: str, payload: PortfolioPatch) -> Portfolio:
    try:
        return store._patch_entity(store.portfolios, portfolio_id, payload, "Portfolio nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(portfolio_id: str) -> None:
    try:
        store.delete_portfolio(portfolio_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
