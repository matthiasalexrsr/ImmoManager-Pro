"""A DATEV export of one owner: every booking with that owner's part, the owners adding up to the whole."""
import csv
import io
from datetime import date
from zipfile import ZipFile

import pytest
from fastapi import HTTPException

from backend.models import ContactCreate
from backend.models_ownership import OwnershipShareCreate
from backend.services import datev_export as datev
from backend.services import ownership
from backend.tests.test_annual_tax_projection import booking
from backend.tests.test_annual_tax_projection import tax_store as tax_store
from backend.tests.test_tax_current_contracts import datev_profile, datev_request


def rows(store, receipt):
    download = datev.prepare_saved_download(store, receipt["id"])
    try:
        with ZipFile(download.path) as archive:
            text = archive.read(receipt["files"][0]["name"]).decode("cp1252")
    finally:
        download.close()
    return [(row[0], row[1]) for row in list(csv.reader(io.StringIO(text), delimiter=";"))[2:]]


def test_an_owners_export_carries_their_part_and_the_owners_add_up_to_the_whole(tax_store):
    store, _, _, properties, _, _ = tax_store
    anna = store.create_contact(ContactCreate(contact_type="owner", first_name="Anna"))
    ben = store.create_contact(ContactCreate(contact_type="owner", first_name="Ben"))
    for owner, percent in ((anna, 60), (ben, 40)):
        ownership.create_share(store, OwnershipShareCreate(owner_contact_id=owner.id, property_id=properties[0].id,
                                                           share_percent=percent), None)
    booking(tax_store, 100.01)
    cost = booking(tax_store, -30.10)
    booking(tax_store, 30.10, day=date(2024, 6, 2), reverses_booking_id=cost.id, payment_text="Storno")
    booking(tax_store, -10, day=date(2024, 6, 3), owner_contact_id=ben.id)        # Ben's own cost
    booking(tax_store, 50, prop=1, day=date(2024, 6, 4))                           # no shares on property 1
    version = datev.create_profile(store, datev_profile(tax_store), "actor")
    assert [owner["name"] for owner in datev.options(store, version["portfolio_id"])["owners"]] == ["Anna", "Ben"]
    whole = datev.create_preview(store, datev_request(version), "actor")
    assert (whole["rows"], whole["income"], whole["expense"]) == (5, "180.11", "40.10")
    assert "owner_contact_id" not in whole
    # without an owner the request reads as before, so earlier repeat keys still match
    assert "owner_contact_id" not in datev.export_row(store, whole["id"]).request_json

    exports = {key: datev.create_preview(store, datev_request(version, owner_contact_id=key, idempotency_key=key), "actor")
               for key in (anna.id, ben.id, "none")}
    anna_export = exports[anna.id]
    assert (anna_export["owner_name"], anna_export["rows"], anna_export["income"], anna_export["expense"]) == (
        "Anna", 3, "78.07", "18.06")
    # the reversal keeps its check against the original booking with the owner's part (same day: by id)
    assert sorted(rows(store, anna_export)) == [("18,06", "H"), ("18,06", "S"), ("60,01", "S")]
    assert (exports[ben.id]["rows"], exports[ben.id]["income"], exports[ben.id]["expense"]) == (4, "52.04", "22.04")
    assert rows(store, exports[ben.id])[-1] == ("10,00", "H")
    assert (exports["none"]["owner_name"], exports["none"]["rows"], exports["none"]["income"]) == ("Ohne Eigentümer", 1, "50.00")
    for flow in ("income", "expense"):
        assert sum(int(export[flow].replace(".", "")) for export in exports.values()) == int(whole[flow].replace(".", ""))

    # the owner is part of the request: the same key with another owner is a different export
    with pytest.raises(HTTPException) as refused:
        datev.create_preview(store, datev_request(version, owner_contact_id=ben.id, idempotency_key=anna.id), "actor")
    assert refused.value.status_code == 409


def test_the_owner_of_an_export_must_be_an_owner(tax_store):
    store, *_ = tax_store
    tenant = store.create_contact(ContactCreate(contact_type="tenant", first_name="Mia"))
    booking(tax_store, 100)
    version = datev.create_profile(store, datev_profile(tax_store), "actor")
    with pytest.raises(HTTPException) as refused:
        datev.create_preview(store, datev_request(version, owner_contact_id=tenant.id), "actor")
    assert refused.value.status_code == 422 and "Eigentümer des Exports" in refused.value.detail
