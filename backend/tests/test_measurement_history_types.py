"""The historical boundary contract rejects invented or ambiguous sources."""

import pytest
from pydantic import ValidationError

from backend.services.measurement_history_types import FactChange, MeasurementCommand
from backend.services.measurement_history_validation import MeasurementIntegrityError, validate_effective


def change(kind="assignment", **updates):
    data = {"kind": kind, "valid_from": "2026-01-01", "valid_until": "2027-01-01"}
    if kind == "assignment":
        data.update(meter_id="m", medium="cold_water", measurement_unit="m³", circuit_path=["water"])
    elif kind == "occupancy":
        data.update(contract_id="c", persons=2)
    elif kind == "selection":
        data.update(allocation_key_id="k", basis="consumption", circuits=[["water"]], confirmed_disjoint=True)
    data.update(updates)
    return FactChange(source_key="source", reason="Original geprüft", data=data)


def test_half_open_intervals_and_decimal_values_are_explicit():
    assert change().data.valid_until.isoformat() == "2027-01-01"
    with pytest.raises(ValidationError):
        change(valid_until="2026-01-01")
    with pytest.raises(ValidationError):
        change("occupancy", persons=2.5)
    with pytest.raises(ValidationError):
        change("occupancy", vacancy=True)
    for value in ("NaN", "Infinity", "-1"):
        with pytest.raises(ValidationError):
            FactChange(source_key="r", reason="Original", data={"kind": "reading", "assignment_key": "a",
                "boundary_date": "2026-01-01", "value": value})


@pytest.mark.parametrize("circuits", [[["main"], ["main", "sub"]], [["main"], ["main"]], [[]]])
def test_overlapping_main_subcircuits_cannot_be_confirmed(circuits):
    with pytest.raises(ValidationError):
        change("selection", circuits=circuits)


def test_approval_needs_a_preserved_document_original():
    with pytest.raises(ValidationError, match="Dokumentoriginal"):
        FactChange(source_key="approval", reason="Accepted", data={"kind": "proration", "assignment_key": "a",
            "valid_from": "2026-01-01", "valid_until": "2027-01-01", "start_reading_id": "r1", "end_reading_id": "r2"})


def test_effective_occupancy_cannot_overlap_and_duplicate_commands_are_ambiguous():
    row = {"source_key": "one", "data": change("occupancy").data.model_dump(mode="json"), "withdrawn": False}
    with pytest.raises(MeasurementIntegrityError, match="überschneiden"):
        validate_effective([row, {**row, "source_key": "two"}])
    with pytest.raises(ValidationError, match="Quellenreihe"):
        MeasurementCommand(expected_revision=0, idempotency_key="one", changes=[change(), change()])
