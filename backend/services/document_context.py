"""Resolve document locations without rewriting historic metadata or duplicating records."""

from sqlalchemy import and_, or_, select

from ..db.orm_models import ContractORM, DocumentORM, UnitORM
from ..models import Document
from ..storage import NotFoundError


def context(store, document):
    def get(getter, identifier):
        if identifier:
            try:
                return getter(identifier)
            except NotFoundError:
                pass
        return None

    contract = get(store.get_contract, document.contract_id)
    unit_id = document.unit_id or (contract.unit_id if contract else None)
    unit = get(store.get_unit, unit_id)
    property_id = document.property_id or (unit.property_id if unit else None) or (contract.property_id if contract else None)
    prop = get(store.get_property, property_id)
    tenant_id = document.tenant_id or (contract.tenant_id if contract else None)
    tenant = get(store.get_tenant, tenant_id)
    return ({"property_id": property_id, "unit_id": unit_id, "contract_id": document.contract_id, "tenant_id": tenant_id},
            {"property": prop.name if prop else None, "unit": unit.label if unit else None,
             "contract": contract.contract_number if contract else None, "tenant": tenant.full_name if tenant else None})


def page(store, *, property_id=None, unit_id=None, contract_id=None, skip=0, limit=100, sort_by=None, descending=False):
    """Apply location filters before pagination, including documents attached only via a child.

    Explicit metadata takes precedence; SQL subqueries retain the request's portfolio scope.
    No join multiplies results and no historic document receives synthetic foreign keys.
    """
    # Legacy internal callers can invoke a router directly, without FastAPI resolving Query defaults.
    property_id, unit_id, contract_id, sort_by = (
        value if isinstance(value, str) else None for value in (property_id, unit_id, contract_id, sort_by))
    skip = skip if isinstance(skip, int) else 0
    limit = limit if isinstance(limit, int) else 100
    if not property_id and not unit_id:
        return store._list_paginated("document", skip=skip, limit=limit, filters={"contract_id": contract_id},
                                     order_by=sort_by, order_desc=descending)
    if hasattr(store, "db"):
        query = store.db.query(DocumentORM)
        if property_id:
            via_unit = DocumentORM.unit_id.in_(select(UnitORM.id).where(UnitORM.property_id == property_id))
            via_contract = DocumentORM.contract_id.in_(select(ContractORM.id).where(ContractORM.property_id == property_id))
            query = query.filter(or_(DocumentORM.property_id == property_id,
                and_(DocumentORM.property_id.is_(None), or_(via_unit,
                    and_(DocumentORM.unit_id.is_(None), via_contract)))))
        if unit_id:
            via_contract = DocumentORM.contract_id.in_(select(ContractORM.id).where(ContractORM.unit_id == unit_id))
            query = query.filter(or_(DocumentORM.unit_id == unit_id,
                                    and_(DocumentORM.unit_id.is_(None), via_contract)))
        if contract_id:
            query = query.filter(DocumentORM.contract_id == contract_id)
        if sort_by in Document.model_fields:
            column = getattr(DocumentORM, sort_by)
            query = query.order_by(column.desc().nullslast() if descending else column.asc().nullsfirst())
        order = (DocumentORM.created_at.desc(), DocumentORM.id.desc()) if descending else (DocumentORM.created_at, DocumentORM.id)
        rows = query.order_by(*order).offset(skip).limit(limit)
        return [Document.model_validate(row, from_attributes=True) for row in rows]

    units = {row.id: row for row in store.list_units()}
    contracts = {row.id: row for row in store.list_contracts()}
    matching = []
    for document in store.list_documents():
        contract = contracts.get(document.contract_id)
        effective_unit = document.unit_id or (contract.unit_id if contract else None)
        unit = units.get(effective_unit)
        effective_property = document.property_id or (unit.property_id if unit else None) or (contract.property_id if contract else None)
        if property_id and effective_property != property_id:
            continue
        if unit_id and effective_unit != unit_id:
            continue
        if contract_id and document.contract_id != contract_id:
            continue
        matching.append(document)
    matching.sort(key=lambda row: (row.created_at, row.id), reverse=descending)
    if sort_by in Document.model_fields:
        matching.sort(key=lambda row: (getattr(row, sort_by) is not None, getattr(row, sort_by)), reverse=descending)
    return matching[skip:skip + limit]
