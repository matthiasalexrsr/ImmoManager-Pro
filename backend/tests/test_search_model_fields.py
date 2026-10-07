"""Search must use the actual shared contact and property schema."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.orm_models import Base
from backend.models import ContactCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import search
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sql"])
def search_store(request, monkeypatch):
    if request.param == "memory":
        store = InMemoryStore()
        monkeypatch.setattr(search, "store", store)
        yield store
        return
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        monkeypatch.setattr(search, "store", store)
        yield store
    engine.dispose()


@pytest.mark.parametrize("query", ["Johanna", "Winkelmann", "Johanna Winkelmann", "Nordlicht Haustechnik"])
def test_contact_names_and_company_are_findable_with_readable_result(search_store, query):
    person = search_store.create_contact(ContactCreate(
        contact_type="supplier", first_name="Johanna", last_name="Winkelmann",
        company_name="Nordlicht Haustechnik", email="service@example.invalid",
    ))
    result = search.global_search(q=query, semantic=False)
    matches = [hit for hit in result["results"] if hit["id"] == person.id]
    assert matches == [{"entity_type": "contact", "id": person.id,
                        "display": "Johanna Winkelmann", "detail": "Nordlicht Haustechnik",
                        "url": "/contacts"}]


@pytest.mark.parametrize("payload,query,label", [
    ({"company_name": "Klarwasser GmbH"}, "klarwasser", "Klarwasser GmbH"),
    ({"last_name": "  Eichhorn  "}, "eichhorn", "Eichhorn"),
    ({"email": "anfrage@example.invalid"}, "anfrage@example.invalid", "anfrage@example.invalid"),
])
def test_contact_without_full_person_name_uses_existing_identity(search_store, payload, query, label):
    person = search_store.create_contact(ContactCreate(**payload))
    result = search.global_search(q=query, semantic=False)
    match = next(hit for hit in result["results"] if hit["id"] == person.id)
    assert match["display"] == label


def test_property_street_and_postal_code_are_searchable(search_store):
    portfolio = search_store.create_portfolio(PortfolioCreate(name="Portfolio"))
    prop = search_store.create_property(PropertyCreate(
        portfolio_id=portfolio.id, name="Am Garten", property_type="residential",
        address_line="Seidenstraße 48", postal_code="64321", city="Darmstadt",
    ))
    for query in ("Seidenstraße", "64321"):
        result = search.global_search(q=query, semantic=False)
        assert any(hit["id"] == prop.id and hit["url"] == f"/properties/{prop.id}"
                   for hit in result["results"])


def test_semantic_property_index_contains_same_address_fields(search_store, monkeypatch):
    portfolio = search_store.create_portfolio(PortfolioCreate(name="Portfolio"))
    prop = search_store.create_property(PropertyCreate(
        portfolio_id=portfolio.id, name="Am Garten", property_type="residential",
        address_line="Seidenstraße 48", postal_code="64321", city="Darmstadt",
    ))
    entries = []
    fake_index = SimpleNamespace(is_available=True, clear=entries.clear,
                                 add_entries=entries.extend, rebuild=lambda: True)
    monkeypatch.setattr(search, "search_index", fake_index)
    search._rebuild_search_index()
    entry = next(item for item in entries if item.entity_id == prop.id)
    assert "Seidenstraße 48" in entry.text
    assert "64321" in entry.text
