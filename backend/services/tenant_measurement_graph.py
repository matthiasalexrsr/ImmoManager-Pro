"""Exact retained occupancy projection inside the coherent privacy snapshot."""

import hashlib

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import exists, or_, select, text

from ..db.measurement_history_models import MeasurementFactORM
from ..db.orm_models import ContractORM
from .measurement_history_recovery import retained_measurement_subject
from .measurement_parent_guards import _available
from .portfolio_scope import scoped_clause

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
    contracts = ContractORM.__table__
    facts = MeasurementFactORM.__table__
    current = select(contracts.c.id).where(contracts.c.tenant_id == tenant_id)
    subject = or_(facts.c.tenant_id == tenant_id, facts.c.contract_id.in_(current))
    clause = scoped_clause(MeasurementFactORM)
    if clause is not None and db.connection().scalar(select(exists(select(facts.c.id).where(subject, ~clause)))):
        raise HTTPException(403, "Der vollständige historische Personenbezug ist mit diesen Portfoliorechten nicht zugänglich.")
    properties = set(db.scalars(select(ContractORM.property_id).where(ContractORM.tenant_id == tenant_id)))
    properties.update(db.scalars(select(MeasurementFactORM.property_id).where(subject).distinct()))
    if db.get_bind().dialect.name == "postgresql":
        for property_id in sorted(properties):
            identifier = int.from_bytes(hashlib.sha256(("measurement:" + property_id).encode()).digest()[:8], "big", signed=True)
            if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:identifier)"), {"identifier": identifier}):
                from .tenant_privacy import PrivacyConflict
                raise PrivacyConflict("Historische Quellen werden gerade bestätigt. Vorschau neu laden und erneut versuchen.")
    # An empty measurement family must not preempt other families' frozen-party
    # checks with a tenant lookup: after a current-contract correction, only the
    # workflow original may still establish that subject's hidden portfolio.
    if db.connection().scalar(select(exists(select(facts.c.id).where(subject)))):
        retained_measurement_subject(store, tenant_id)
