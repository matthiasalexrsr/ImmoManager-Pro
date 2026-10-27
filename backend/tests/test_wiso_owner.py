"""The WISO worksheet of each owner: their part of every row, adding up to the row to the cent."""
import csv
import io
from datetime import date
from zipfile import ZipFile

import pytest

from backend.models import ContactCreate
from backend.models_ownership import OwnershipShareCreate
from backend.services import annual_tax_projection, ownership
from backend.services import annual_tax_storage as storage
from backend.services.annual_tax_export import prepare_download
from backend.services.wiso_preparation import saved_preparation, saved_preparation_by_owner
from backend.tax_models import AnnualTaxPreflightCreate
from backend.tests.test_annual_tax_projection import booking, save_command
from backend.tests.test_annual_tax_projection import tax_store as tax_store  # noqa: F401
from backend.tests.test_wiso_preparation import wiso_cash, wiso_profile


@pytest.fixture(autouse=True)
def completed_year(monkeypatch):
    monkeypatch.setattr(annual_tax_projection, "local_today", lambda: date(2027, 1, 2))


def saved(store, fixture):
    profile = storage.create_profile(store, wiso_profile(fixture), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=profile["id"], as_of=date(2026, 12, 31))
    checked = storage.preflight(store, command)
    return checked, storage.create_projection(store, save_command(command, checked), "actor")


def test_each_owners_sheet_carries_their_part_of_the_rows(tax_store):
    store, _, _, properties, *_ = tax_store
    anna = store.create_contact(ContactCreate(contact_type="owner", first_name="Anna"))
    ben = store.create_contact(ContactCreate(contact_type="owner", first_name="Ben"))
    for owner, percent in ((anna, 60), (ben, 40)):
        ownership.create_share(store, OwnershipShareCreate(owner_contact_id=owner.id, property_id=properties[0].id,
                                                           share_percent=percent), None)
    wiso_cash(tax_store)
    booking(tax_store, -10, category=1, day=date(2026, 5, 1), owner_contact_id=ben.id)     # Ben's own cost
    booking(tax_store, 5.67, prop=1, day=date(2026, 4, 1))                                  # no shares on property 1
    checked, projection = saved(store, tax_store)
    report, owners = saved_preparation_by_owner(store, projection["id"])
    assert saved_preparation(store, projection["id"]) == report == checked["wiso_preparation"]
    assert [sheet["owner_name"] for sheet in owners] == ["Anna", "Ben", "Ohne Eigentümer"]
    sheets = {sheet["owner_name"]: sheet for sheet in owners}
    assert sheets["Ohne Eigentümer"]["rows"] == [{
        "object_number": 2, "property_id": properties[1].id, "property_name": "Property 1",
        "target_object_label": "Reviewed target 2", "treatment": "income", "form_line": "User form income",
        "target_label": "Manually checked rent label", "mapping_complete": True, "amount_cents": "567", "amount_eur": "5,67"}]
    # Ben bears 40 % of the shared costs (20,09) and his own 10,00
    ben_costs = next(row for row in sheets["Ben"]["rows"] if row["treatment"] == "expense")
    assert ben_costs["amount_eur"] == "18,04" and sheets["Anna"]["totals"]["expense_cents"] == "1205"
    for flow in ("income_cents", "expense_cents"):
        assert sum(int(sheet["totals"][flow]) for sheet in owners) == int(report["mapped_totals"][flow])

    download = prepare_download(store, projection["id"])
    try:
        with ZipFile(download.path) as archive:
            text = archive.read("manual-transfer-worksheet-by-owner.csv").decode("utf-8-sig")
    finally:
        download.close()
    table = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert table[0][:3] == ["tax_year", "owner_contact_id", "owner_name"]
    assert [(row[2], row[7], row[10]) for row in table[1:]] == [
        (sheet["owner_name"], row["treatment"], row["amount_cents"]) for sheet in owners for row in sheet["rows"]]


def test_without_owners_there_are_no_sheets(tax_store):
    store, *_ = tax_store
    wiso_cash(tax_store)
    _, projection = saved(store, tax_store)
    assert saved_preparation_by_owner(store, projection["id"])[1] == []
    download = prepare_download(store, projection["id"])
    try:
        with ZipFile(download.path) as archive:
            assert "manual-transfer-worksheet-by-owner.csv" not in archive.namelist()
    finally:
        download.close()


def test_one_booking_with_an_owner_splits_every_amount_the_rest_unowned(tax_store):
    store, *_ = tax_store
    ben = store.create_contact(ContactCreate(contact_type="owner", first_name="Ben"))
    wiso_cash(tax_store)
    booking(tax_store, -10, category=1, day=date(2026, 5, 1), owner_contact_id=ben.id)
    checked, projection = saved(store, tax_store)
    split = {(row["owner_name"], row["treatment"]): int(row["amount_cents"]) for row in checked["owner_split"]}
    assert split == {("Ben", "expense"): 1000, ("Ohne Eigentümer", "income"): 10000, ("Ohne Eigentümer", "expense"): 2009}
    assert len(saved_preparation_by_owner(store, projection["id"])[1]) == 2
