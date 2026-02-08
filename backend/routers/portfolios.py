from fastapi import APIRouter, HTTPException, status

from ..models import Portfolio, PortfolioCreate
from ..storage import InMemoryStore, NotFoundError

router = APIRouter(prefix="/portfolios", tags=["Portfolios"])
store = InMemoryStore()


@router.get("", response_model=list[Portfolio])
def list_portfolios() -> list[Portfolio]:
    return store.list_portfolios()


@router.post("", response_model=Portfolio, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: PortfolioCreate) -> Portfolio:
    return store.create_portfolio(payload)


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


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(portfolio_id: str) -> None:
    try:
        store.delete_portfolio(portfolio_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
