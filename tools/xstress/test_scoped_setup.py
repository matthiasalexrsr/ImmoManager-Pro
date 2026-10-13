"""The harness must provision scoped users and stop before invalid fixture cascades."""

import pytest

from tools.xstress import bad_input, core, roles
from tools.xstress.timeline import Simulation
from tools.xstress.world import build_world


@pytest.mark.parametrize("status, content", [(400, {"detail": "hidden parent"}), (500, {"detail": "error"}),
                                             (None, None), (201, {}), (201, None)])
def test_required_entity_stops_on_rejection_or_missing_id(status, content):
    client = object.__new__(core.Client)
    client.username = "verwalter"
    client.call = lambda *args, **kwargs: (status, content)
    with pytest.raises(core.FixtureSetupError, match="required POST /units failed"):
        client.require_entity("POST", "/units", {"property_id": "missing"})


def test_setup_stops_before_dependent_calls_when_portfolio_creation_fails():
    class RejectedOwner:
        def require_entity(self, method, path, body, **kwargs):
            assert (method, path) == ("POST", "/portfolios")
            raise core.FixtureSetupError("portfolio rejected")

    world = build_world(units=4, years=1)
    sim = Simulation(world, {"owner": RejectedOwner(), "verwalter": object()}, core.Findings(), 2026)
    with pytest.raises(core.FixtureSetupError, match="portfolio rejected"):
        sim.setup()
    assert all(unit.id is None for unit in world.units)
    assert all(tenant.id is None for tenant in world.tenants)
    assert not sim.created


@pytest.mark.parametrize("prepare", [bad_input.references, lambda client: roles._prepare({"verwalter": client})])
def test_phase_setup_fails_clearly_when_scoped_prerequisites_are_missing(prepare):
    class NoAccess:
        def all(self, *args, **kwargs):
            return []

    with pytest.raises(core.FixtureSetupError, match="active contract"):
        prepare(NoAccess())


def test_real_setup_grants_generated_portfolios_and_excludes_future_portfolios(tmp_path):
    """Real isolated HTTP setup, with every non-owner still in selected mode."""
    server, findings, users = core.Server(tmp_path), core.Findings(), {}
    try:
        server.start()
        users = core.setup_users(server, findings)
        assert users["verwalter"].all("/portfolios") == []
        world = build_world(units=4, years=1)
        sim = Simulation(world, users, findings, 2026)
        sim.setup()
        expected = {pf.id for pf in world.portfolios}
        assert len(expected) == len(world.portfolios)
        for username, client in users.items():
            if username == "owner":
                continue
            me = client.require_entity("GET", "/auth/me")
            assert me["portfolio_access"] == "selected"
            assert set(me["portfolio_ids"]) == expected
            assert {p["id"] for p in client.all("/portfolios")} == expected
            assert len(client.all("/units")) == len(world.units)
        assert all(unit.id for unit in world.units)
        assert sim.created
        assert not [item for item in findings.items if item["severity"] != "HINWEIS"]

        owner = users["owner"]
        hidden = owner.require_entity("POST", "/portfolios", {"name": "Outside generated scope"})
        account = owner.require_entity("POST", "/accounts", {"portfolio_id": hidden["id"], "name": "Hidden cash",
                                                                "account_type": "cash"})
        for username, client in users.items():
            if username == "owner":
                continue
            assert hidden["id"] not in {p["id"] for p in client.all("/portfolios")}
            status, _ = client.call("GET", f"/accounts/{account['id']}", expect=(404,))
            assert status == 404
            status, _ = client.call("GET", "/data/export", expect=(403,))
            assert status == 403
        assert roles.MATRIX["Daten exportieren"] == {"eigentuemer"}
        roles.matrix(users, findings)
        assert not [item for item in findings.items if item["severity"] != "HINWEIS"]
    finally:
        for client in users.values():
            client.http.close()
        server.stop()
