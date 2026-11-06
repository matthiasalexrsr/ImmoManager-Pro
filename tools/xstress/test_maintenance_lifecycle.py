"""The real project API requires audited closure, including historical fixtures."""
from tools.xstress import core
from tools.xstress.timeline import create_maintenance_case


def test_historical_completed_fixture_uses_the_actual_project_transition(tmp_path):
    server, findings = core.Server(tmp_path), core.Findings()
    try:
        server.start()
        users = core.setup_users(server, findings)
        owner = users['owner']
        portfolio = owner.require_entity('POST', '/portfolios', {'name': 'Wartungsprobe'})
        core.assign_portfolios(users, [portfolio['id']])
        prop = owner.require_entity('POST', '/properties', {'portfolio_id': portfolio['id'],
            'name': 'Synthetisches Haus Stuttgart', 'property_type': 'residential'})
        case = create_maintenance_case(users['hausmeister'], {'property_id': prop['id'],
            'title': 'Abgeschlossene synthetische Wartung', 'status': 'completed'})
        assert case['status'] == 'completed'
        project = users['hausmeister'].ok('GET', f'/maintenance/{case["id"]}/project')
        assert project and not [f for f in findings.items if f['severity'] != 'HINWEIS']
    finally:
        server.stop()
