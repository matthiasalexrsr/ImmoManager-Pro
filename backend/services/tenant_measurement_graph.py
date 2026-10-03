"""Exact retained occupancy projection inside the coherent privacy snapshot."""

import hashlib

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select, text

from ..db.measurement_history_models import MeasurementFactORM
from ..db.orm_models import ContractORM
from .measurement_history_recovery import retained_measurement_subject
from .measurement_parent_guards import _available

PERSONAL_FIELDS = {
    "measurement_facts": ["frozen tenant and contract references", "original occupancy", "reason", "evidence references"],
    "measurement_commands": ["actor_id", "revision", "created_at", "request_hash"],
}


def append_measurement_graph(store, graph):
    graph["measurement_facts"], graph["measurement_commands"] = [], []
    if _available(store):
        retained = retained_measurement_subject(store, graph["tenant"]["id"])
        graph["measurement_facts"] = jsonable_encoder(retained["facts"])
        graph["measurement_commands"] = jsonable_encoder(retained["commands"])
    graph["scope"]["measurement_history"] = (
        "Bestätigte historische Belegungsquellen und ihre Originalbezüge bleiben erhalten. "
        "Gemeinsame technische Messdaten verbleiben auf Objektebene; fremde Mietparteien "
        "und komplette gemeinsame Befehlsinhalte werden nicht ausgegeben.")
    return graph


def lock_measurement_subject(store, tenant_id):
    """After account/operational fence, before domain rows; no new schema."""
    if not _available(store):
        return
    if not hasattr(store, "db"):
        retained_measurement_subject(store, tenant_id)
        return  # Shared account/domain lock already spans confirmation.
    db = store.db
    # Current contracts cover the very first concurrent historical confirmation.
    current = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
    subject = or_(MeasurementFactORM.tenant_id == tenant_id, MeasurementFactORM.contract_id.in_(current))
    properties = set(db.scalars(select(ContractORM.property_id).where(ContractORM.tenant_id == tenant_id)))
    properties.update(db.scalars(select(MeasurementFactORM.property_id).where(subject).distinct()))
    if db.get_bind().dialect.name == "postgresql":
        for property_id in sorted(properties):
            identifier = int.from_bytes(hashlib.sha256(("measurement:" + property_id).encode()).digest()[:8], "big", signed=True)
            if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:identifier)"), {"identifier": identifier}):
                from .tenant_privacy import PrivacyConflict
                raise PrivacyConflict("Historische Quellen werden gerade bestätigt. Vorschau neu laden und erneut versuchen.")
    retained_measurement_subject(store, tenant_id)  # Complete frozen/current scope before any profile change.
