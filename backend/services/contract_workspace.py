"""Authorized contract search with bounded reads and stable live keyset pages.

No global count, offset, getAll or unrelated reference list is necessary.
Pages are coherent read snapshots, not an immutable multi-page export.
"""

import base64
import hashlib
import hmac
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from functools import cmp_to_key
from heapq import nsmallest
from time import time
from typing import Any

from sqlalchemy import and_, or_, select

from ..config import settings
from ..db.booking_order import bytewise_id
from ..db.orm_models import ContractORM, PropertyORM, TenantORM, UnitORM
from .concurrency import etag
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .contract_workspace_types import (
    ContractWorkspaceError,
    ContractWorkspaceItem,
    ContractWorkspacePage,
    ContractWorkspaceQuery,
)
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause

CURSOR_SECONDS = 3600
TEXT_FIELDS = {"contract_number", "status", "property_name", "unit_label", "tenant_name"}
DATE_FIELDS = {"start_date", "end_date"}


def today() -> date:
    return datetime.now(timezone.utc).date()


def maximum_page_size() -> int:
    value = getattr(settings, "contract_workspace_page_max_size", 500)
    if type(value) is not int or value <= 0:
        raise RuntimeError("CONTRACT_WORKSPACE_PAGE_MAX_SIZE must be a positive integer")
    return value


def _binding(query: ContractWorkspaceQuery, reference_date: date) -> str:
    scope = current_scope()
    value = {
        "query": query.model_dump(mode="json", exclude={"cursor"}),
        "reference_date": reference_date.isoformat(),
        "scope": None
        if scope is None
        else {
            "user_id": scope.user_id,
            "role": scope.role,
            "unrestricted": scope.unrestricted,
            "portfolio_ids": scope.portfolio_ids,
        },
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(decoded) != value:
        raise ValueError
    return decoded


def _signature(value: bytes) -> bytes:
    return hmac.new(settings.jwt_secret_key.encode(), b"immo-contract-workspace-v1\0" + value, hashlib.sha256).digest()


def _cursor(query: ContractWorkspaceQuery, item: ContractWorkspaceItem, reference_date: date) -> str:
    value = getattr(item, query.sort_by)
    if isinstance(value, date):
        value = value.isoformat()
    stamp = int(time())
    payload = json.dumps(
        {
            "v": 1,
            "binding": _binding(query, reference_date),
            "reference_date": reference_date.isoformat(),
            "value": value,
            "id": item.id,
            "issued": stamp,
            "expires": stamp + CURSOR_SECONDS,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return _b64(payload) + "." + _b64(_signature(payload))


def _position(query: ContractWorkspaceQuery) -> tuple[date, tuple[Any, str] | None]:
    if query.cursor is None:
        return today(), None
    try:
        encoded, mac = query.cursor.split(".")
        payload = _unb64(encoded)
        if not hmac.compare_digest(_unb64(mac), _signature(payload)):
            raise ValueError
        body = json.loads(payload)
        if not isinstance(body, dict) or set(body) != {
            "v",
            "binding",
            "reference_date",
            "value",
            "id",
            "issued",
            "expires",
        }:
            raise ValueError
        if type(body["v"]) is not int or body["v"] != 1:
            raise ValueError
        if type(body["issued"]) is not int or type(body["expires"]) is not int:
            raise ValueError
        stamp = int(time())
        if body["issued"] > stamp + 60 or body["expires"] - body["issued"] != CURSOR_SECONDS:
            raise ValueError
        if stamp >= body["expires"]:
            raise ContractWorkspaceError(
                "cursor_expired", "Die Vertragsseite ist abgelaufen. Bitte die erste Seite neu laden."
            )
        reference_date = date.fromisoformat(body["reference_date"])
        if reference_date.isoformat() != body["reference_date"]:
            raise ValueError
        if not hmac.compare_digest(body["binding"], _binding(query, reference_date)):
            raise ContractWorkspaceError(
                "cursor_filter_mismatch",
                "Filter, Sortierung, Seitengröße oder Zugriffsrechte wurden geändert. Bitte die erste Seite laden.",
            )
        identifier, value = body["id"], body["value"]
        if not isinstance(identifier, str) or not identifier:
            raise ValueError
        if value is not None:
            if query.sort_by in DATE_FIELDS:
                value = date.fromisoformat(value)
            elif query.sort_by in TEXT_FIELDS:
                if not isinstance(value, str):
                    raise ValueError
            elif type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError
        return reference_date, (value, identifier)
    except ContractWorkspaceError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        raise ContractWorkspaceError(
            "cursor_invalid", "Die Vertragsseite konnte nicht geprüft werden. Bitte die erste Seite neu laden."
        ) from None


def _statement(query: ContractWorkspaceQuery, reference_date: date, after, scope):
    contracts, properties, units, tenants = (
        model.__table__ for model in (ContractORM, PropertyORM, UnitORM, TenantORM)
    )
    labels = {
        "property_name": properties.c.name,
        "unit_label": units.c.label,
        "tenant_name": tenants.c.full_name,
        "unit_cold_rent": units.c.cold_rent,
    }
    statement = select(contracts, *(value.label(name) for name, value in labels.items()))
    for table, identity, extra in (
        (properties, contracts.c.property_id, None),
        (units, contracts.c.unit_id, units.c.property_id == contracts.c.property_id),
        (tenants, contracts.c.tenant_id, None),
    ):
        conditions = [table.c.id == identity]
        visibility = scoped_clause(table, scope=scope)
        if visibility is not None:
            conditions.append(visibility)
        if extra is not None:
            conditions.append(extra)
        statement = statement.outerjoin(table, and_(*conditions))
    visibility = scoped_clause(contracts, scope=scope)
    if visibility is not None:
        statement = statement.where(visibility)
    for name in ("property_id", "unit_id", "tenant_id", "status"):
        value = getattr(query, name)
        if value is not None:
            statement = statement.where(contracts.c[name] == value)
    if query.date_from is not None:
        statement = statement.where(contracts.c.start_date >= query.date_from)
    if query.date_to is not None:
        statement = statement.where(contracts.c.end_date <= query.date_to)
    if query.view == "ending_soon":
        statement = statement.where(
            contracts.c.status == "active",
            contracts.c.end_date > reference_date,
            contracts.c.end_date <= reference_date + timedelta(days=90),
        )
    elif query.view == "no_deposit":
        statement = statement.where(or_(contracts.c.deposit_amount.is_(None), contracts.c.deposit_amount == 0))
    if query.search:
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(
            or_(
                *(
                    bytewise_id(UnicodeCasefold(column)).like(f"%{term}%", escape="\\")
                    for column in (
                        contracts.c.contract_number,
                        labels["property_name"],
                        labels["unit_label"],
                        labels["tenant_name"],
                    )
                )
            )
        )
    sort = labels[query.sort_by] if query.sort_by in labels else contracts.c[query.sort_by]
    if query.sort_by in TEXT_FIELDS:
        sort = bytewise_id(sort)
    identifier = bytewise_id(contracts.c.id)
    descending = query.sort_order == "desc"
    if after is not None:
        value, last_id = after
        id_after = identifier < last_id if descending else identifier > last_id
        if value is None:
            predicate = and_(sort.is_(None), id_after)
        else:
            greater = sort < value if descending else sort > value
            predicate = or_(sort.is_(None), greater, and_(sort == value, id_after))
        statement = statement.where(predicate)
    return statement.order_by(
        sort.desc().nulls_last() if descending else sort.asc().nulls_last(),
        identifier.desc() if descending else identifier.asc(),
    ).limit(query.page_size + 1)


def _compare(first, second, descending: bool) -> int:
    value, identifier = first
    other, other_id = second
    if (value is None) != (other is None):
        return 1 if value is None else -1
    if isinstance(value, str):
        value, other = value.encode("utf-8"), other.encode("utf-8")
    if value != other:
        result = -1 if value < other else 1
    else:
        result = (identifier.encode("utf-8") > other_id.encode("utf-8")) - (
            identifier.encode("utf-8") < other_id.encode("utf-8")
        )
    return -result if descending else result


def _item(values) -> ContractWorkspaceItem:
    return ContractWorkspaceItem.model_validate(
        {**values, "edit_etag": etag("contracts", values["id"], values["updated_at"])}
    )


def _memory_page(store, query: ContractWorkspaceQuery, reference_date: date, after, scope):
    raw = object.__getattribute__(store, "__dict__")
    descending = query.sort_order == "desc"

    def matches():
        for contract in raw["contracts"].values():
            if not memory_visible(store, "contracts", contract, scope=scope):
                continue
            if any(
                getattr(query, name) is not None and getattr(contract, name) != getattr(query, name)
                for name in ("property_id", "unit_id", "tenant_id", "status")
            ):
                continue
            if query.date_from and contract.start_date < query.date_from:
                continue
            if query.date_to and (contract.end_date is None or contract.end_date > query.date_to):
                continue
            if query.view == "ending_soon" and (
                contract.status != "active"
                or contract.end_date is None
                or not reference_date < contract.end_date <= reference_date + timedelta(days=90)
            ):
                continue
            if query.view == "no_deposit" and contract.deposit_amount not in (None, 0):
                continue
            prop, unit, tenant = (
                raw[name].get(getattr(contract, field))
                for name, field in (("properties", "property_id"), ("units", "unit_id"), ("tenants", "tenant_id"))
            )
            if prop is not None and not memory_visible(store, "properties", prop, scope=scope):
                prop = None
            if unit is not None and (
                unit.property_id != contract.property_id or not memory_visible(store, "units", unit, scope=scope)
            ):
                unit = None
            # A freshly visible exact contract is itself the authoritative
            # tenant-visibility anchor. Do not scan all other contracts here.
            labels = {
                "property_name": getattr(prop, "name", None),
                "unit_label": getattr(unit, "label", None),
                "tenant_name": getattr(tenant, "full_name", None),
                "unit_cold_rent": getattr(unit, "cold_rent", None),
            }
            if query.search and not any(
                query.search.casefold() in (value or "").casefold()
                for value in (
                    contract.contract_number,
                    labels["property_name"],
                    labels["unit_label"],
                    labels["tenant_name"],
                )
            ):
                continue
            values = {**contract.model_dump(), **labels}
            position = (values[query.sort_by], contract.id)
            if after is not None and _compare(position, after, descending) <= 0:
                continue
            yield values

    def compare_rows(first: dict[str, Any], second: dict[str, Any]) -> int:
        return _compare((first[query.sort_by], first["id"]), (second[query.sort_by], second["id"]), descending)

    return [_item(value) for value in nsmallest(query.page_size + 1, matches(), key=cmp_to_key(compare_rows))]


def get_contract_workspace_page(store, query: ContractWorkspaceQuery) -> ContractWorkspacePage:
    if query.page_size > maximum_page_size():
        raise ContractWorkspaceError(
            "page_size_exceeded", "Bitte eine kleinere Vertragsseite verwenden. Alle weiteren Seiten bleiben verfügbar."
        )
    scope = current_scope()
    refresh_scope(scope)
    reference_date, after = _position(query)
    if hasattr(store, "db"):
        if query.search:
            ensure_sqlite_casefold(store.db)
        with store.db.no_autoflush, store.db.execute(_statement(query, reference_date, after, scope)) as rows:
            selected = [_item(dict(row)) for row in rows.mappings()]
    else:
        from .payments import _memory_lock

        with _memory_lock:
            selected = _memory_page(store, query, reference_date, after, scope)
    refresh_scope(scope)
    has_more = len(selected) > query.page_size
    items = selected[: query.page_size]
    return ContractWorkspacePage(
        items=items,
        has_more=has_more,
        reference_date=reference_date,
        next_cursor=_cursor(query, items[-1], reference_date) if has_more else None,
    )
