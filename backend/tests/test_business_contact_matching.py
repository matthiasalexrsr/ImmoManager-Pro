"""Contact SQL prefilters must be supersets of the exact Python normalization."""

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import ContactCreate, PortfolioCreate

API = "/api/v1/work-center"


@pytest.fixture(autouse=True)
def clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.fixture
def owner():
    user = auth.register_user("contacts", "contacts@example.test", "Büro", "Secret123", "eigentuemer")
    return user, TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


@pytest.mark.parametrize("saved,candidate,reason", [
    ({"phone": "+49 30 123 DW45"}, {"phone": "493012345"}, "phone"),
    ({"mobile": "0123; Anschluss 45"}, {"mobile": "012345"}, "phone"),
    ({"email": "Straße@EXAMPLE.test"}, {"email": "STRASSE@example.test"}, "email"),
    ({"email": "\tINFO@example.test\n"}, {"email": "info@EXAMPLE.test"}, "email"),
    ({"first_name": "JÖRG", "last_name": "Straße", "street": "Weg 1", "zip_code": "12345"},
     {"first_name": "jörg", "last_name": "STRASSE", "street": "weg 1", "zip_code": "12345"}, "name_address"),
    ({"last_name": "Müller", "street": "Straße 10", "zip_code": "12345\t"},
     {"last_name": "MÜLLER", "street": "STRASSE 10", "zip_code": "12345"}, "name_address"),
    ({"last_name": "Meyer", "street": "Weg 1", "zip_code": "12345"},
     {"last_name": "meyer", "street": "weg 1", "zip_code": "12345"}, "name_address"),
    ({"first_name": "Max", "last_name": "Anderer", "company_name": "Straße GmbH", "street": "Weg 1", "zip_code": "12345"},
     {"first_name": "Anna", "last_name": "Meyer", "company_name": "STRASSE GmbH", "street": "weg 1", "zip_code": "12345"},
     "name_address"),
])
def test_contact_normalization_finds_unusual_phone_casefold_null_names_and_company_branch(owner, saved, candidate, reason):
    target = store.create_contact(ContactCreate(**saved))
    # Unusual input broadens the SQL candidate set, never the exact result.
    store.create_contact(ContactCreate(first_name="Unbeteiligt", email="Andere@Straße.test", phone="123 DW987",
        last_name="Fremd", company_name="Fremde Firma", street="Straße 999", zip_code="99999"))
    result = owner[1].post(API + "/duplicates/check", json={"kind": "contact", "candidate": candidate, "limit": 1})
    assert result.status_code == 200, result.text
    assert [(row["id"], row["reason"]) for row in result.json()["items"]] == [(target.id, reason)]
    assert result.json()["has_more"] is False


def test_contact_unicode_matches_page_without_cutoff_or_false_positives(owner):
    targets = {store.create_contact(ContactCreate(email="Straße@example.test", first_name=f"Treffer {number}")).id
               for number in range(5)}
    for number in range(25):
        store.create_contact(ContactCreate(email=f"fremd{number}@Straße.test", phone=f"123 DW{number}"))
    seen: list[str] = []
    cursor = None
    while True:
        result = owner[1].post(API + "/duplicates/check", json={"kind": "contact", "candidate": {
            "email": "STRASSE@example.test"}, "limit": 2, **({"cursor": cursor} if cursor else {})})
        assert result.status_code == 200, result.text
        data = result.json()
        seen.extend(row["id"] for row in data["items"])
        if not data["has_more"]:
            break
        cursor = data["next_cursor"]
    assert set(seen) == targets and len(seen) == len(targets)


def test_unusual_candidates_preserve_shared_contact_read_policy_for_selected_portfolios(owner):
    north = store.create_portfolio(PortfolioCreate(name="Nord"))
    south = store.create_portfolio(PortfolioCreate(name="Süd"))
    clients = []
    contacts = []
    for label, portfolio in (("north", north), ("south", south)):
        user = auth.register_user(label, f"{label}@example.test", label, "Secret123", "verwalter",
            portfolio_access="selected", portfolio_ids=[portfolio.id])
        client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})
        saved = client.post("/api/v1/contacts", json={"first_name": label, "phone": "+49 30 123 DW45",
            "email": "Straße@example.test"})
        assert saved.status_code == 201, saved.text
        clients.append(client)
        contacts.append(saved.json()["id"])
    for client in clients:
        for candidate in ({"email": "STRASSE@example.test"}, {"phone": "493012345"}):
            result = client.post(API + "/duplicates/check", json={"kind": "contact", "candidate": candidate})
            assert result.status_code == 200, result.text
            # contacts are deliberately SHARED_READ across portfolios. The
            # conservative selector must preserve that existing read policy.
            assert {row["id"] for row in result.json()["items"]} == set(contacts)
