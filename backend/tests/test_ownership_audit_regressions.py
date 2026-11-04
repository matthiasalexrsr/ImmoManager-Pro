"""Independent invariants reported as F02/F03, on memory and the SQL matrix."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from test_ownership_changes import estate  # noqa: F401

from backend.dependencies import store
from backend.models import Booking
from backend.models_ownership import OwnershipShareCreate
from backend.services.data_snapshot import SnapshotError, export_snapshot, prepare_import
from backend.services.maintenance_projects import work
from backend.services.maintenance_rows import Rows
from backend.services.ownership import Ownership, create_share


@pytest.mark.parametrize("field", ["owner_contact_id", "property_id", "unit_id", "share_percent", "valid_from", "valid_to", "note"])
def test_changed_ended_share_prevents_revert_without_any_writes(estate, field):  # noqa: F811
    original = estate["share"]("Matthias", 100, valid_from="2026-01-01")
    sale = estate["transfer"]("Matthias", [("Linda", 100)], "2026-02-01")
    closed = next(s for s in estate["call"]("GET", "/ownership-shares") if s["id"] == original["id"])
    changes = {"owner_contact_id": estate["people"]["Richard"], "property_id": estate["other"],
               "unit_id": estate["units"]["WE 1"], "share_percent": 40, "valid_from": "2026-01-02",
               "valid_to": "2026-01-30", "note": "Nachträglich geändert"}
    body = {key: closed[key] for key in OwnershipShareCreate.model_fields}
    estate["call"]("PUT", "/ownership-shares/" + original["id"], {**body, field: changes[field]})
    before = estate["call"]("GET", "/ownership-shares")
    estate["call"]("POST", f"/ownership-shares/transfers/{sale['id']}/revert", expected=409)
    assert estate["call"]("GET", "/ownership-shares") == before


def test_unchanged_ended_share_cannot_be_reopened_into_new_ownership(estate):  # noqa: F811
    estate["share"]("Matthias", 100)
    sale = estate["transfer"]("Matthias", [], "2026-02-01", kind="sale_external")
    estate["share"]("Richard", 100, valid_from="2026-02-01")
    before = estate["call"]("GET", "/ownership-shares")
    estate["call"]("POST", f"/ownership-shares/transfers/{sale['id']}/revert", expected=409)
    assert estate["call"]("GET", "/ownership-shares") == before


def test_legacy_journal_does_not_guess_missing_ended_share_state(estate):  # noqa: F811
    estate["share"]("Matthias", 100)
    sale = estate["transfer"]("Matthias", [("Linda", 100)], "2026-02-01")
    changes = deepcopy(sale["changes"])
    for entry in changes["ended"]:
        entry.pop("before")
        entry.pop("after")
    with work(store, None, ()) as unit:
        Rows.of(unit).update("ownership_transfers", sale["id"], changes=changes)
    estate["call"]("POST", f"/ownership-shares/transfers/{sale['id']}/revert", expected=409)


@pytest.mark.parametrize("invalid", ["different_property", "invalid_shape"])
def test_imported_journal_cannot_move_shares_into_another_property_or_break_history(estate, invalid):  # noqa: F811
    estate["share"]("Matthias", 100)
    sale = estate["transfer"]("Matthias", [("Linda", 100)], "2026-02-01")
    estate["share"]("Richard", 100, prop=estate["other"])
    changes = deepcopy(sale["changes"])
    if invalid == "different_property":
        changes["ended"][0]["before"]["property_id"] = estate["other"]
    else:
        changes["ended"] = "unvollständiges Altdatum"
    with work(store, None, ()) as unit:
        Rows.of(unit).update("ownership_transfers", sale["id"], changes=changes)
    before = estate["call"]("GET", "/ownership-shares")
    estate["call"]("POST", f"/ownership-shares/transfers/{sale['id']}/revert", expected=409)
    assert estate["call"]("GET", "/ownership-shares") == before
    from backend.services.ownership import history
    journal = history(store, estate["house"])
    assert not journal["transfers"][0]["revertible"]


def test_owner_change_journal_keeps_latest_undo_order_on_a_frozen_clock(estate, monkeypatch):  # noqa: F811
    from backend.services import maintenance_rows
    from backend.services.ownership import history

    estate["share"]("Matthias", 100)
    fixed = maintenance_rows.stamp("ownership_transfers")
    monkeypatch.setattr(maintenance_rows, "stamp", lambda table: fixed)
    first = estate["transfer"]("Matthias", [("Linda", 100)], "2026-02-01")
    second = estate["transfer"]("Linda", [("Richard", 100)], "2026-03-01")
    assert datetime.fromisoformat(second["created_at"]) > datetime.fromisoformat(first["created_at"])
    assert [row["id"] for row in history(store, estate["house"])["transfers"] if row["revertible"]] == [second["id"]]
    estate["call"]("POST", f"/ownership-shares/transfers/{second['id']}/revert")
    estate["call"]("POST", f"/ownership-shares/transfers/{first['id']}/revert")


def incoming(world, owner, percent=100, **changes):
    return {"id": str(uuid4()), "owner_contact_id": world["people"][owner], "property_id": world["house"],
            "share_percent": percent, **changes}


@pytest.mark.parametrize("kind", ["sum", "same_owner", "wrong_property", "not_owner"])
def test_invalid_ownership_snapshot_is_rejected_atomically(estate, kind):  # noqa: F811
    if kind == "sum":
        shares = [incoming(estate, "Matthias"), incoming(estate, "Linda")]
    elif kind == "same_owner":
        shares = [incoming(estate, "Matthias", 20), incoming(estate, "Matthias", 20)]
    elif kind == "wrong_property":
        shares = [incoming(estate, "Matthias", property_id=estate["other"], unit_id=estate["units"]["WE 1"])]
    else:
        contact = estate["post"]("/contacts", {"contact_type": "other", "first_name": "Kein Eigentümer"})
        shares = [incoming(estate, "Matthias", owner_contact_id=contact["id"])]
    before = export_snapshot(store)
    payload = {"ownership_shares": shares, "portfolios": [{"id": str(uuid4()), "name": "Darf nicht entstehen"}]}
    with pytest.raises(SnapshotError):
        prepare_import(store, payload, replace=False).apply()
    after = export_snapshot(store)
    before.pop("exported_at")
    after.pop("exported_at")
    assert after == before


def test_valid_adjacent_intervals_and_independent_unit_shares_import(estate):  # noqa: F811
    shares = [incoming(estate, "Matthias", valid_to="2026-01-31"),
              incoming(estate, "Matthias", valid_from="2026-02-01"),
              incoming(estate, "Linda", unit_id=estate["units"]["WE 1"])]
    assert prepare_import(store, {"ownership_shares": shares}, replace=False).apply()["imported"]["ownership_shares"] == 3


def test_prepared_import_revalidates_current_ownership_at_commit(estate):  # noqa: F811
    prepared = prepare_import(store, {"ownership_shares": [incoming(estate, "Linda")]}, replace=False)
    create_share(store, OwnershipShareCreate(owner_contact_id=estate["people"]["Matthias"],
                                             property_id=estate["house"], share_percent=100), None)
    with pytest.raises(SnapshotError):
        prepared.apply()
    shares = estate["call"]("GET", "/ownership-shares")
    assert len(shares) == 1 and shares[0]["owner_contact_id"] == estate["people"]["Matthias"]


def test_prepared_import_cannot_replace_a_new_record_with_the_same_id(estate):  # noqa: F811
    proposed = incoming(estate, "Linda")
    prepared = prepare_import(store, {"ownership_shares": [proposed]}, replace=False)
    # A distinct import wins the race after the first preview. The losing plan
    # must not overwrite the winner in memory or partially import other rows.
    winner = {**proposed, "owner_contact_id": estate["people"]["Matthias"]}
    prepare_import(store, {"ownership_shares": [winner]}, replace=False).apply()
    with pytest.raises(SnapshotError, match="Zielbestand"):
        prepared.apply()
    shares = estate["call"]("GET", "/ownership-shares")
    assert len(shares) == 1 and shares[0]["owner_contact_id"] == winner["owner_contact_id"]


def test_smaller_than_representable_share_is_not_rounded_to_zero(estate):  # noqa: F811
    estate["post"]("/ownership-shares", incoming(estate, "Matthias", percent=0.0000000001), expected=422)


@pytest.mark.parametrize("amount,pieces,owners", [(0.02, [0.01, 0.01], 2),
    (0.07, [0.02, 0.01, 0.04], 3), (-0.05, [0.01, 0.03, 0.01], 3)])
def test_partial_reversals_consume_original_owner_cents_exactly(estate, amount, pieces, owners):  # noqa: F811
    people = ["Matthias", "Linda", "Richard"][:owners]
    for index, person in enumerate(people):
        estate["share"](person, (50 if owners == 2 else 33.3334 if index == 2 else 33.3333))
    account = estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "Stornotest", "account_type": "bank"})
    original = estate["post"]("/bookings", {"account_id": account["id"], "property_id": estate["house"],
                       "booking_date": "2026-01-01", "amount": amount})
    rows = [original]
    for part in pieces:
        rows.append(estate["post"](f"/bookings/{original['id']}/reverse", {"booking_date": "2026-01-02", "amount": part}))
        view = Ownership(store)
        # No owner can lose more cents than they had in the original booking.
        net = {estate["people"][person]: sum((view.booking_split(store.get_booking(row["id"])).get(
            estate["people"][person], Decimal(0)) for row in rows), Decimal(0)) for person in people}
        assert all(value >= 0 if amount > 0 else value <= 0 for value in net.values())
    assert all(value == 0 for value in net.values())


def test_new_partial_reversal_cannot_reassign_already_published_cents_on_a_clock_tick(estate, monkeypatch):  # noqa: F811
    from backend import storage
    from backend.repositories import base, finance_repo

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
            return value if tz is not None else value.replace(tzinfo=None)

    estate["share"]("Matthias", 50)
    estate["share"]("Linda", 50)
    account = estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "Clock test", "account_type": "bank"})
    original = estate["post"]("/bookings", {"account_id": account["id"], "property_id": estate["house"],
                       "booking_date": "2026-01-01", "amount": .02})
    # Deliberately reverse UUID order while both calls see the same wall-clock.
    ids = iter(["ffffffff-ffff-4fff-8fff-ffffffffffff", "00000000-0000-4000-8000-000000000000"])
    monkeypatch.setattr(storage, "datetime", FrozenClock)
    monkeypatch.setattr(finance_repo, "datetime", FrozenClock)
    if hasattr(store, "db"):
        monkeypatch.setattr(base, "_generate_id", lambda: next(ids))
    else:
        monkeypatch.setattr(storage, "_generate_id", lambda: next(ids))
    first = estate["post"](f"/bookings/{original['id']}/reverse", {"booking_date": "2026-01-02", "amount": .01})
    assert datetime.fromisoformat(first["created_at"]) > datetime.fromisoformat(original["created_at"])
    before = Ownership(store).booking_split(store.get_booking(first["id"]))
    second = estate["post"](f"/bookings/{original['id']}/reverse", {"booking_date": "2026-01-03", "amount": .01})
    assert datetime.fromisoformat(second["created_at"]) > datetime.fromisoformat(first["created_at"])
    assert Ownership(store).booking_split(store.get_booking(first["id"])) == before


@pytest.mark.parametrize("invalid", ["over_reversed", "wrong_sign", "wrong_assignment", "earlier_day"])
def test_snapshot_rejects_invalid_reversal_families_atomically(estate, invalid):  # noqa: F811
    account = estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "Import Storno", "account_type": "bank"})
    original = estate["post"]("/bookings", {"account_id": account["id"], "property_id": estate["house"],
                       "booking_date": "2026-01-01", "amount": .02})
    reversal = {**original, "id": str(uuid4()), "reverses_booking_id": original["id"], "amount": -.01,
                "booking_date": "2026-01-02"}
    changes = {"over_reversed": {"amount": -.03}, "wrong_sign": {"amount": .01},
               "wrong_assignment": {"owner_contact_id": estate["people"]["Richard"]},
               "earlier_day": {"booking_date": "2025-12-31"}}
    before = export_snapshot(store)
    with pytest.raises(SnapshotError, match="Storno"):
        prepare_import(store, {"bookings": [{**reversal, **changes[invalid]}]}, replace=False).apply()
    after = export_snapshot(store)
    before.pop("exported_at")
    after.pop("exported_at")
    assert after == before


def test_inconsistent_legacy_reversal_reports_a_conflict_instead_of_dividing_by_zero(estate):  # noqa: F811
    from fastapi import HTTPException

    account = estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "Altdaten Storno", "account_type": "bank"})
    original = estate["post"]("/bookings", {"account_id": account["id"], "property_id": estate["house"],
                       "booking_date": "2026-01-01", "amount": .02})
    with work(store, None, ()) as unit:
        rows = Rows.of(unit)
        legacy = Booking(**{**original, "id": str(uuid4()), "amount": -.03,
                            "reverses_booking_id": original["id"], "booking_date": "2026-01-02"})
        rows.add("bookings", legacy)
    with pytest.raises(HTTPException) as error:
        Ownership(store).booking_split(store.get_booking(legacy.id))
    assert error.value.status_code == 409 and "Stornofolge" in error.value.detail
