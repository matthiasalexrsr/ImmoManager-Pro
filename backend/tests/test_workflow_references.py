"""Real private choice HTTP requests; no first-10k projection or user export."""

from datetime import date
from threading import Event, Thread

import pytest
from sqlalchemy import event, insert

from backend import auth
from backend.config import settings
from backend.db.orm_models import PropertyORM
from backend.models import (
    ContractCreate,
    DocumentCreate,
    HandoverProtocolCreate,
    MeterCreate,
    MeterReadingCreate,
    PropertyCreate,
    UnitCreate,
)
from backend.routers import workflow_references as router
from backend.services import reference_cursor
from backend.services.portfolio_scope import scope_context
from backend.services.workflow_references import WorkflowReferenceQuery, workflow_reference_choices
from backend.tests.test_portfolio_access_http import access_http as _access_http

access_http = _access_http
PREFIX = "/api/v1/workflow-references/"


def insert_properties(store, template, count):
    values = [template.model_copy(update={"id": f"choice-{index:05d}", "name": "Ordinary property"})
              for index in range(count)]
    values[0] = values[0].model_copy(update={"name": "Späte Straße_% Älteste", "address_line": "Private street"})
    if hasattr(store, "db"):
        store.db.execute(insert(PropertyORM), [row.model_dump() for row in values])
        store.db.commit()
    else:
        store.properties.update({row.id: row for row in values})


def test_http_choices_require_auth_and_scope_all_kinds(access_http):
    client, _, owner, member, _, _, properties, contracts, *_ = access_http
    assert client.get(PREFIX + "properties").status_code == 401
    page = client.get(PREFIX + "properties", headers=member).json()
    assert [row["id"] for row in page["items"]] == [properties[0].id]
    for kind in ("units", "contracts", "documents", "handover-protocols", "meter-readings", "meters", "users"):
        response = client.get(PREFIX + kind, headers=member, params={"property_id": properties[0].id})
        assert response.status_code == 200, (kind, response.text)
        assert response.headers["cache-control"] == "private, no-store"
        assert properties[1].id not in response.text
        assert contracts[1].id not in response.text
        forbidden = client.get(PREFIX + kind, headers=member, params={"property_id": properties[1].id})
        assert forbidden.status_code == 404, (kind, forbidden.text)
    assert len(client.get(PREFIX + "properties", headers=owner).json()["items"]) == 2


def test_search_after_ten_thousand_uses_bounded_sql_and_identical_unicode_literals(access_http):
    client, store, _, member, _, _, properties, *_ = access_http
    with scope_context(None):
        insert_properties(store, properties[0], 10003)
    statements = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "FROM properties" in statement and "immo_contract_casefold" in statement:
            statements.append((statement, parameters))

    engine = store.db.get_bind() if hasattr(store, "db") else None
    if engine:
        event.listen(engine, "before_cursor_execute", capture)
    try:
        result = client.get(PREFIX + "properties", headers=member,
                            params={"search": "STRASSE_% ÄLTESTE", "page_size": 7})
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", capture)
    assert result.status_code == 200, result.text
    assert [row["id"] for row in result.json()["items"]] == ["choice-00000"]
    assert result.json()["has_more"] is False
    if engine:
        assert len(statements) == 1
        assert "LIMIT" in statements[0][0] and "COUNT(" not in statements[0][0]
        assert statements[0][1][-2:] == (8, 0)


def test_complete_keyset_traversal_pins_selected_and_rejects_changed_cursor(access_http, monkeypatch):
    client, store, owner, _, _, _, properties, *_ = access_http
    with scope_context(None):
        insert_properties(store, properties[0], 37)
    params = {"search": "property", "page_size": 7, "selected_id": "choice-00000"}
    seen = []
    first_cursor = None
    while True:
        result = client.get(PREFIX + "properties", headers=owner, params=params)
        assert result.status_code == 200, result.text
        page = result.json()
        assert page["selected"]["id"] == "choice-00000"
        seen.extend(row["id"] for row in page["items"])
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        first_cursor = first_cursor or page["next_cursor"]
        params["cursor"] = page["next_cursor"]
    assert seen == [f"choice-{index:05d}" for index in reversed(range(1, 37))]
    for changes in ({"search": "other"}, {"page_size": 8}, {"selected_id": "choice-00001"},
                    {"property_id": properties[0].id}, {"cursor": first_cursor + "x"}):
        result = client.get(PREFIX + "properties", headers=owner, params={**params, "cursor": first_cursor, **changes})
        assert result.status_code == 422, result.text
    monkeypatch.setattr(reference_cursor, "time", lambda: 10**12)
    assert client.get(PREFIX + "properties", headers=owner, params={**params, "cursor": first_cursor}).status_code == 422


def test_parent_conflicts_and_hidden_selected_are_checked(access_http):
    client, _, _, member, _, _, properties, contracts, *_ = access_http
    for kind in ("units", "contracts", "documents", "handover-protocols", "meter-readings", "meters"):
        result = client.get(PREFIX + kind, headers=member, params={"selected_id": contracts[1].id})
        assert result.status_code == 200
        assert result.json()["selected"] is None
    assert client.get(PREFIX + "contracts", headers=member, params={"contract_id": contracts[1].id}).status_code == 404
    result = client.get(PREFIX + "contracts", headers=member,
                        params={"property_id": properties[0].id, "unit_id": contracts[1].unit_id})
    assert result.status_code == 404
    result = client.get(PREFIX + "units", headers=member,
                        params={"property_id": properties[1].id, "unit_id": contracts[0].unit_id})
    assert result.status_code == 422


def test_only_finalized_matching_protocols_and_readings_are_offered(access_http):
    client, store, _, member, _, _, properties, contracts, *_ = access_http
    with scope_context(None):
        records = []
        for direction, status in (("move_out", "finalized"), ("move_in", "finalized"), ("move_out", "draft")):
            protocol = store.create_handover_protocol(HandoverProtocolCreate(contract_id=contracts[0].id,
                unit_id=contracts[0].unit_id, protocol_type=direction, status=status, protocol_date=date(2026, 10, 2),
                notes="SYNTHETIC_PRIVATE_PROTOCOL_NOTE"))
            reading = store.create_meter_reading(MeterReadingCreate(handover_id=protocol.id, meter_type="electricity",
                reading_value=12.5, meter_number="READING_%", notes="SYNTHETIC_PRIVATE_READING_NOTE"))
            records.append((protocol, reading))
        document = store.create_document(DocumentCreate(title="Linked original", contract_id=contracts[0].id,
            file_url="uploads/synthetic.txt", description="SYNTHETIC_PRIVATE_DOCUMENT_NOTE"))
        meter = store.create_meter(MeterCreate(unit_id=contracts[0].unit_id, meter_type="electricity", serial_number="METER-%"))
    params = {"property_id": properties[0].id, "unit_id": contracts[0].unit_id, "contract_id": contracts[0].id, "direction": "move_out"}
    for kind, expected in (("handover-protocols", records[0][0].id), ("meter-readings", records[0][1].id)):
        result = client.get(PREFIX + kind, headers=member, params=params)
        assert result.status_code == 200, result.text
        assert [row["id"] for row in result.json()["items"]] == [expected]
        assert "SYNTHETIC_PRIVATE" not in result.text
    for kind, expected in (("documents", document.id), ("meters", meter.id)):
        result = client.get(PREFIX + kind, headers=member, params={key: value for key, value in params.items() if key != "direction"})
        assert result.status_code == 200, result.text
        assert [row["id"] for row in result.json()["items"]] == [expected]
        assert result.json()["items"][0]["property_id"] == properties[0].id
        assert "SYNTHETIC_PRIVATE" not in result.text


def test_assignment_candidates_are_minimal_active_authorized_operations_people(access_http, monkeypatch):
    client, _, owner, member, _, portfolios, properties, *_ = access_http
    matching = auth.register_user("work-tech", "work-tech@example.test", "Straße_% Specialist", "StrongPass123!", "techniker",
        portfolio_access="selected", portfolio_ids=[portfolios[0].id])
    other = auth.register_user("other-tech", "other-tech@example.test", "Other specialist", "StrongPass123!", "techniker",
        portfolio_access="selected", portfolio_ids=[portfolios[1].id])
    accounting = auth.register_user("accounting", "accounting@example.test", "Accounting", "StrongPass123!", "buchhaltung")
    inactive = auth.register_user("inactive-tech", "inactive-tech@example.test", "Inactive", "StrongPass123!", "techniker")
    auth.update_user(inactive.id, {"is_active": False})
    monkeypatch.setattr(auth._user_store, "list_all", lambda: pytest.fail("full account export used"))
    params = {"property_id": properties[0].id}
    result = client.get(PREFIX + "users", headers=member, params=params)
    assert result.status_code == 200, result.text
    candidates = result.json()["items"]
    assert matching.id in {row["id"] for row in candidates}
    assert {other.id, accounting.id, inactive.id}.isdisjoint({row["id"] for row in candidates})
    assert all(set(row) == {"id", "full_name", "role"} for row in candidates)
    assert "example.test" not in result.text and "hashed_password" not in result.text and "totp" not in result.text
    search = client.get(PREFIX + "users", headers=owner, params={**params, "search": "STRASSE_%"})
    assert [row["id"] for row in search.json()["items"]] == [matching.id]
    assert client.get(PREFIX + "users", headers=owner).status_code == 422
    readonly = {"Authorization": "Bearer " + auth.create_access_token(accounting.id)}
    assert client.get(PREFIX + "users", headers=readonly, params=params).status_code == 403


def test_page_budget_is_configuration_and_invalid_queries_are_recoverable(access_http, monkeypatch):
    client, _, owner, *_ = access_http
    monkeypatch.setattr(settings, "workflow_reference_page_budget", 12000)
    assert client.get(PREFIX + "properties", headers=owner, params={"page_size": 10001}).status_code == 200
    for params in ({"page_size": 12001}, {"page_size": 0}, {"property_id": "\0"}, {"search": "\0"},
                   {"page_size": "true"}, {"table": "users"}, {"direction": "move_out"}):
        assert client.get(PREFIX + "properties", headers=owner, params=params).status_code == 422, params
    assert client.get(PREFIX + "unknown", headers=owner).status_code == 422
    assert client.get(PREFIX + "properties", headers=owner).status_code == 200
    with pytest.raises(ValueError):
        WorkflowReferenceQuery(search="\ud800")


@pytest.mark.parametrize("change", ["role", "token"])
def test_late_revocation_blocks_prepared_private_choices(access_http, monkeypatch, change):
    client, _, _, member, actor, _, properties, *_ = access_http
    original = router.workflow_reference_choices

    def revoke_after_query(*args):
        result = original(*args)
        if change == "role":
            auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        else:
            auth.revoke_token(member["Authorization"][7:])
        return result

    monkeypatch.setattr(router, "workflow_reference_choices", revoke_after_query)
    result = client.get(PREFIX + "properties", headers=member)
    assert result.status_code == (403 if change == "role" else 401), result.text
    assert properties[0].name not in result.text


def test_cursor_does_not_follow_changed_actor_grants(access_http):
    client, store, owner, member, actor, portfolios, properties, *_ = access_http
    with scope_context(None):
        insert_properties(store, properties[0], 8)
    page = client.get(PREFIX + "properties", headers=member, params={"page_size": 2}).json()
    assert page["has_more"]
    assert client.patch(f"/api/v1/auth/users/{actor.id}", headers=owner,
                        json={"portfolio_access": "selected", "portfolio_ids": [portfolios[1].id]}).status_code == 200
    result = client.get(PREFIX + "properties", headers=member, params={"page_size": 2, "cursor": page["next_cursor"]})
    assert result.status_code == 422
    assert properties[0].id not in result.text


def test_direct_query_does_not_commit_callers_open_sql_work(access_http):
    _, store, _, _, actor, *_ = access_http
    if not hasattr(store, "db"):
        pytest.skip("Caller SQL transaction only")
    prop = next(iter(store.db.query(PropertyORM)))
    prop.name = "UNCOMMITTED_CALLER_VALUE"
    page = workflow_reference_choices(store, "properties", WorkflowReferenceQuery(), actor.id)
    assert "UNCOMMITTED_CALLER_VALUE" not in str(page)
    assert store.db.dirty
    store.db.rollback()


def test_memory_scan_and_normal_creates_share_one_coherent_read_boundary(access_http, monkeypatch):
    client, store, _, headers, _, _, properties, contracts, *_ = access_http
    if hasattr(store, "db"):
        pytest.skip("Memory collection synchronization only")
    from backend.services import workflow_references as service
    from backend.services.payments import _memory_lock

    contract = contracts[0]
    protocol = store.create_handover_protocol(HandoverProtocolCreate(
        contract_id=contract.id, unit_id=contract.unit_id, protocol_type="move_out", protocol_date=date(2026, 10, 2)))
    creates = [
        (store.create_property, PropertyCreate(name="Concurrent property", property_type="residential", portfolio_id=properties[0].portfolio_id)),
        (store.create_unit, UnitCreate(property_id=properties[0].id, label="Concurrent unit", unit_type="apartment")),
        (store.create_contract, ContractCreate(**{**contract.model_dump(exclude={"id", "created_at", "updated_at"}),
                                                "contract_number": "Concurrent draft", "status": "draft"})),
        (store.create_document, DocumentCreate(title="Concurrent document", property_id=properties[0].id, file_url="uploads/synthetic.txt")),
        (store.create_handover_protocol, HandoverProtocolCreate(contract_id=contract.id, unit_id=contract.unit_id, protocol_type="move_out", protocol_date=date(2026, 10, 2))),
        (store.create_meter_reading, MeterReadingCreate(handover_id=protocol.id, meter_type="electricity", reading_value=1.0)),
        (store.create_meter, MeterCreate(unit_id=contract.unit_id, meter_type="electricity")),
    ]
    original = service._memory_choice
    for create, payload in creates:
        scanning, release_scan, writer_started, writer_done = Event(), Event(), Event(), Event()
        responses, errors, probes = [], [], []

        def pause_scan(*args):
            if not scanning.is_set():
                scanning.set()
                assert release_scan.wait(5), "reader was not released"
            return original(*args)

        def read():
            try:
                responses.append(client.get(PREFIX + "properties", headers=headers))
            except BaseException as exc:
                errors.append(exc)

        def write():
            try:
                acquired = _memory_lock.acquire(blocking=False)
                probes.append(acquired)
                if acquired:
                    _memory_lock.release()
                writer_started.set()
                create(payload)
            except BaseException as exc:
                errors.append(exc)
            finally:
                writer_done.set()

        monkeypatch.setattr(service, "_memory_choice", pause_scan)
        reader, writer = Thread(target=read), Thread(target=write)
        reader.start()
        try:
            assert scanning.wait(5), "reader did not reach its source scan"
            writer.start()
            assert writer_started.wait(5)
            assert probes == [False], "source scan did not hold the domain boundary"
            assert not writer_done.wait(0.1), create.__name__ + " bypassed the boundary"
        finally:
            release_scan.set()
            reader.join(5)
            if writer.ident is not None:
                writer.join(5)
        assert not reader.is_alive() and not writer.is_alive(), "account/domain lock order deadlocked"
        assert errors == [], (create.__name__, errors)
        assert len(responses) == 1 and responses[0].status_code == 200
        assert writer_done.is_set()
