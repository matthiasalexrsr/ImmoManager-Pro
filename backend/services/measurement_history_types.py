"""Explicit half-open historical intervals; no conversion of current metadata."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Interval(Strict):
    valid_from: date
    valid_until: date

    @model_validator(mode="after")
    def ordered(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("Zeitraum benötigt ein ausschließliches Ende nach dem Beginn.")
        return self


class MeterAssignment(Interval):
    kind: Literal["assignment"] = "assignment"
    meter_id: str = Field(min_length=1)
    medium: str = Field(min_length=1)
    measurement_unit: str = Field(min_length=1)
    circuit_path: tuple[str, ...] = Field(min_length=1)

    @field_validator("medium", "measurement_unit")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("Medium und Maßeinheit benötigen exakte Originalangaben.")
        return value

    @field_validator("circuit_path")
    @classmethod
    def circuit(cls, value):
        if any(not part.strip() or part != part.strip() for part in value):
            raise ValueError("Messkreisabschnitte dürfen nicht leer sein.")
        return value


class BoundaryReading(Strict):
    kind: Literal["reading"] = "reading"
    assignment_key: str = Field(min_length=1)
    boundary_date: date
    value: Decimal = Field(ge=0, allow_inf_nan=False)


class OccupancyInterval(Interval):
    kind: Literal["occupancy"] = "occupancy"
    contract_id: str | None = None
    persons: int = Field(ge=0, strict=True)
    vacancy: bool = False

    @model_validator(mode="after")
    def explicit_vacancy(self):
        if self.vacancy != (self.contract_id is None):
            raise ValueError("Leerstand benötigt keinen Vertrag; Belegung benötigt einen tatsächlichen Vertrag.")
        if self.vacancy and self.persons != 0:
            raise ValueError("Leerstand hat keine Bewohner.")
        return self


class AllocationSelection(Interval):
    kind: Literal["selection"] = "selection"
    allocation_key_id: str = Field(min_length=1)
    basis: Literal["consumption", "person_count"]
    circuits: tuple[tuple[str, ...], ...] = ()
    confirmed_disjoint: bool = False

    @model_validator(mode="after")
    def selection(self):
        if self.basis == "consumption":
            if not self.circuits or not self.confirmed_disjoint:
                raise ValueError("Verbrauch benötigt ausdrücklich bestätigte überschneidungsfreie Messkreise.")
            for path in self.circuits:
                MeterAssignment.circuit(path)
                if not path:
                    raise ValueError("Leerer Messkreis.")
            for index, path in enumerate(self.circuits):
                if any(path[:len(other)] == other or other[:len(path)] == path
                       for other in self.circuits[index + 1:]):
                    raise ValueError("Haupt- und Unterzähler oder doppelte Messkreise dürfen nicht zugleich ausgewählt werden.")
        elif self.circuits:
            raise ValueError("Personentage verwenden Belegungsabschnitte, keine Messkreise.")
        return self


class ProrationApproval(Interval):
    kind: Literal["proration"] = "proration"
    assignment_key: str = Field(min_length=1)
    start_reading_id: str = Field(min_length=1)
    end_reading_id: str = Field(min_length=1)


FactData = Annotated[MeterAssignment | BoundaryReading | OccupancyInterval | AllocationSelection | ProrationApproval,
    Field(discriminator="kind")]


class FactChange(Strict):
    source_key: str = Field(min_length=1)
    predecessor_id: str | None = None
    reason: str = Field(min_length=1)
    withdrawn: bool = False
    evidence_version_ids: tuple[str, ...] = ()
    data: FactData

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Erfassung/Korrektur benötigt eine nachvollziehbare Begründung.")
        return value.strip()

    @model_validator(mode="after")
    def evidence(self):
        if len(self.evidence_version_ids) != len(set(self.evidence_version_ids)):
            raise ValueError("Dokumentoriginal ist mehrfach angegeben.")
        if self.data.kind == "proration" and not self.evidence_version_ids:
            raise ValueError("Zeitaufteilung benötigt ein verknüpftes Dokumentoriginal der Freigabe.")
        if self.withdrawn and not self.predecessor_id:
            raise ValueError("Rücknahme benötigt die vorherige Fassung.")
        return self


class MeasurementCommand(Strict):
    expected_revision: int = Field(ge=0, strict=True)
    idempotency_key: str = Field(min_length=1)
    changes: tuple[FactChange, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sources(self):
        if len({change.source_key for change in self.changes}) != len(self.changes):
            raise ValueError("Ein Befehl darf jede Quellenreihe nur einmal ändern.")
        return self
