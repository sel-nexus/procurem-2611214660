"""Cross-feature approval journeys using the real API and persistent SQLite."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import connect
from app.main import create_app


@pytest.fixture
def database_path():
    """Give each journey a fresh file that can survive app restarts."""
    with TemporaryDirectory(prefix='procurem-integration-', dir=Path.home()) as folder:
        yield str(Path(folder) / 'integration.db')


def login(client, name):
    """Switch the session to a seeded user."""
    response = client.post('/api/v1/auth/login', json={
        'email': f'{name}@procurem.demo', 'password': 'Demo@1234',
    })
    assert response.status_code == 200, response.text


def message(client, text, action):
    """Submit a structured proposal through the assistant endpoint."""
    return client.post('/api/v1/assistant/messages', json={'message': text, 'action': action})


def sign(client, approval_id, meaning='Approved', password='Demo@1234'):
    """Submit a password-confirmed approval decision."""
    return client.post(f'/api/v1/approvals/{approval_id}/sign', json={
        'meaning': meaning, 'reason': 'Reviewed the proposal carefully', 'password': password,
    })


def detail(client, resource, record_id):
    """Read a record through the public records service."""
    response = client.get(f'/api/v1/records/{resource}/{record_id}')
    assert response.status_code == 200, response.text
    return response.json()


def notification_for(client, approval_id):
    """Find the caller's notification for an approval."""
    response = client.get('/api/v1/notifications', params={'page_size': 100})
    assert response.status_code == 200, response.text
    matching = [item for item in response.json()['items'] if item['link'] == f'/approvals/{approval_id}']
    assert len(matching) == 1
    return matching[0]


def test_assistant_sourcing_creation_approval_and_restart(database_path):
    settings = Settings(database_path=database_path)
    with TestClient(create_app(settings)) as client:
        login(client, 'sourcing')
        response = message(client, 'Create a sourcing event', {
            'kind': 'sourcing_create', 'details': {
                'title': 'Laboratory instrument renewal', 'event_type': 'RFP',
                'estimated_value_usd': '12000.00', 'end_date': '2028-01-01',
            },
        })
        assert response.status_code == 200, response.text
        result = response.json()
        approval_id = result['answer']['approval_id']
        conversation_id = result['conversation_id']
        approval = client.get(f'/api/v1/approvals/{approval_id}')
        assert approval.status_code == 200
        proposal = approval.json()
        event_id = proposal['subject_id']
        assert (proposal['approval_type'], proposal['risk'], proposal['status']) == ('sourcing_create', 'high', 'pending')
        assert proposal['current'] == {} and proposal['proposed']['title'] == 'Laboratory instrument renewal'
        assert detail(client, 'sourcing', event_id)['item']['status'] == 'pending_approval'
        assert sign(client, approval_id).status_code == 403

        login(client, 'compliance')
        assert sign(client, approval_id).status_code == 403
        login(client, 'proc.manager')
        assert notification_for(client, approval_id)['is_read'] == 0
        assert sign(client, approval_id, password='wrong').status_code == 422
        assert detail(client, 'sourcing', event_id)['item']['status'] == 'pending_approval'
        first = sign(client, approval_id)
        assert first.status_code == 200 and first.json()['status'] == 'pending_second'
        assert len(first.json()['signatures']) == 1
        assert detail(client, 'sourcing', event_id)['item']['status'] == 'pending_approval'
        assert sign(client, approval_id).status_code == 403

        login(client, 'compliance')
        assert notification_for(client, approval_id)['is_read'] == 0
        final = sign(client, approval_id)
        assert final.status_code == 200 and final.json()['status'] == 'approved'
        assert [s['role'] for s in final.json()['signatures']] == ['procurement_manager', 'compliance']
        event = detail(client, 'sourcing', event_id)['item']
        assert event['status'] == 'active' and event['title'] == 'Laboratory instrument renewal'
        audit = client.get('/api/v1/audit', params={'action': 'sign', 'page_size': 100})
        assert audit.status_code == 200
        rows = [r for r in audit.json()['items'] if r['record_id'] == str(approval_id) and r['record_type'] == 'approval']
        assert len(rows) == 2 and {r['role'] for r in rows} == {'procurement_manager', 'compliance'}
        assert all('Demo@1234' not in r['detail'] for r in rows)
        login(client, 'sourcing')
        assert notification_for(client, approval_id)['body'] == 'Your request was approved.'
        with closing(connect(database_path)) as db:
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='create_sourcing_event' AND record_id=?", (str(event_id),)).fetchone()[0] == 1
            before = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                      for table in ('users', 'suppliers', 'sourcing_events', 'approvals', 'signatures', 'notifications')}

    # A new application instance runs the actual startup and idempotent seeder.
    with TestClient(create_app(settings)) as restarted:
        login(restarted, 'sourcing')
        assert detail(restarted, 'sourcing', event_id)['item']['status'] == 'active'
        persisted = restarted.get(f'/api/v1/approvals/{approval_id}')
        assert persisted.status_code == 200 and persisted.json()['status'] == 'approved'
        assert len(persisted.json()['signatures']) == 2
        assert notification_for(restarted, approval_id)['body'] == 'Your request was approved.'
        history = restarted.get(f'/api/v1/assistant/conversations/{conversation_id}')
        assert history.status_code == 200 and history.json()['messages'][1]['answer']['approval_id'] == approval_id
        with closing(connect(database_path)) as db:
            after = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in before}
            assert after == before
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='seed'").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='sign' AND record_id=?", (str(approval_id),)).fetchone()[0] == 2


def test_assistant_award_rejection_then_high_value_approval(database_path):
    settings = Settings(database_path=database_path)
    with TestClient(create_app(settings)) as client:
        # Clear the seeded pending award using the public decision route.
        login(client, 'proc.manager')
        seeded = sign(client, 2, 'Rejected')
        assert seeded.status_code == 200 and seeded.json()['status'] == 'rejected'
        login(client, 'sourcing')
        event = detail(client, 'sourcing', 1)
        assert event['item']['status'] == 'active' and event['item']['winning_supplier_id'] is None
        bid = event['relations']['bids'][0]
        response = message(client, 'Award the sourcing event', {
            'kind': 'sourcing_award', 'event_id': 1, 'details': {'bid_id': bid['id']},
        })
        assert response.status_code == 200, response.text
        approval_id = response.json()['answer']['approval_id']
        proposal = client.get(f'/api/v1/approvals/{approval_id}')
        assert proposal.status_code == 200
        assert (proposal.json()['approval_type'], proposal.json()['risk'], proposal.json()['status']) == ('sourcing_award', 'high', 'pending')
        assert proposal.json()['proposed']['winning_supplier_id'] == bid['supplier_id']
        assert sign(client, approval_id).status_code == 403
        login(client, 'compliance')
        assert sign(client, approval_id).status_code == 403
        login(client, 'proc.manager')
        assert notification_for(client, approval_id)['is_read'] == 0
        first = sign(client, approval_id)
        assert first.status_code == 200 and first.json()['status'] == 'pending_second'
        unchanged = detail(client, 'sourcing', 1)['item']
        assert (unchanged['status'], unchanged['winning_supplier_id']) == ('active', None)
        assert sign(client, approval_id).status_code == 403
        login(client, 'compliance')
        assert notification_for(client, approval_id)['is_read'] == 0
        final = sign(client, approval_id)
        assert final.status_code == 200 and final.json()['status'] == 'approved'
        assert [s['meaning'] for s in final.json()['signatures']] == ['Approved', 'Approved']
        awarded = detail(client, 'sourcing', 1)['item']
        assert (awarded['status'], awarded['winning_supplier_id']) == ('awarded', bid['supplier_id'])
        audit = client.get('/api/v1/audit', params={'action': 'sign', 'page_size': 100})
        assert audit.status_code == 200
        assert len([r for r in audit.json()['items'] if r['record_id'] == str(approval_id)]) == 2
        login(client, 'sourcing')
        assert notification_for(client, approval_id)['body'] == 'Your request was approved.'
        with closing(connect(database_path)) as db:
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='request_award' AND record_id='1'").fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?', (approval_id,)).fetchone()[0] == 2
    with TestClient(create_app(settings)) as restarted:
        login(restarted, 'sourcing')
        award = detail(restarted, 'sourcing', 1)['item']
        assert (award['status'], award['winning_supplier_id']) == ('awarded', bid['supplier_id'])
        decision = restarted.get(f'/api/v1/approvals/{approval_id}')
        assert decision.status_code == 200 and decision.json()['status'] == 'approved'
        assert len(decision.json()['signatures']) == 2
        assert notification_for(restarted, approval_id)['body'] == 'Your request was approved.'
        with closing(connect(database_path)) as db:
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='sign' AND record_id=?", (str(approval_id),)).fetchone()[0] == 2


def test_assistant_requisition_and_supplier_cross_feature_decisions(database_path):
    with TestClient(create_app(Settings(database_path=database_path))) as client:
        login(client, 'analyst')
        response = message(client, 'Create a requisition', {
            'kind': 'requisition', 'details': {
                'supplier_id': 1, 'title': 'Integration lab supplies', 'reason': 'Restock supplies',
                'lines': [{'description': 'Vials', 'quantity': 2, 'unit_price': '125.00'}],
            },
        })
        assert response.status_code == 200, response.text
        req_approval = response.json()['answer']['approval_id']
        proposal = client.get(f'/api/v1/approvals/{req_approval}')
        assert proposal.status_code == 200
        req_id = proposal.json()['subject_id']
        assert (proposal.json()['status'], proposal.json()['risk']) == ('pending', 'low')
        requisition = detail(client, 'requisitions', req_id)
        assert requisition['item']['status'] == 'pending_approval'
        assert requisition['item']['total_amount_usd'] == '250.00'
        assert requisition['relations']['lines'][0]['description'] == 'Vials'
        assert sign(client, req_approval).status_code == 403
        login(client, 'proc.manager')
        assert notification_for(client, req_approval)['is_read'] == 0
        decision = sign(client, req_approval)
        assert decision.status_code == 200 and decision.json()['status'] == 'approved'
        assert detail(client, 'requisitions', req_id)['item']['status'] == 'approved'
        login(client, 'analyst')
        assert notification_for(client, req_approval)['body'] == 'Your request was approved.'

        # A high-risk supplier edit is a different downstream application path.
        login(client, 'category.mgr')
        original = detail(client, 'suppliers', 1)['item']
        response = message(client, 'Edit the supplier', {
            'kind': 'supplier_edit', 'supplier_id': 1,
            'details': {'risk': 'high', 'contact_name': 'New lab contact'},
        })
        assert response.status_code == 200, response.text
        supplier_approval = response.json()['answer']['approval_id']
        proposal = client.get(f'/api/v1/approvals/{supplier_approval}')
        assert proposal.status_code == 200
        assert proposal.json()['current']['risk'] == original['risk']
        assert proposal.json()['proposed']['risk'] == 'high'
        assert proposal.json()['status'] == 'pending' and proposal.json()['risk'] == 'high'
        assert detail(client, 'suppliers', 1)['item']['contact_name'] == original['contact_name']
        login(client, 'proc.manager')
        assert notification_for(client, supplier_approval)['is_read'] == 0
        first = sign(client, supplier_approval)
        assert first.status_code == 200 and first.json()['status'] == 'pending_second'
        assert detail(client, 'suppliers', 1)['item']['risk'] == original['risk']
        login(client, 'compliance')
        assert notification_for(client, supplier_approval)['is_read'] == 0
        final = sign(client, supplier_approval)
        assert final.status_code == 200 and final.json()['status'] == 'approved'
        supplier = detail(client, 'suppliers', 1)['item']
        assert (supplier['risk'], supplier['contact_name']) == ('high', 'New lab contact')
        login(client, 'category.mgr')
        assert notification_for(client, supplier_approval)['body'] == 'Your request was approved.'
        with closing(connect(database_path)) as db:
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='create_requisition' AND record_id=?", (str(req_id),)).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='submit_requisition' AND record_id=?", (str(req_id),)).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='propose_supplier_edit' AND record_id='1'").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM audit_log WHERE action='sign' AND record_id=?", (str(supplier_approval),)).fetchone()[0] == 2


def test_natural_requisition_approval_journey_and_failed_signature(database_path):
    """A natural request remains pending after a bad signature, then completes."""
    request = ('Please create a requisition: supplier: Thermo Fisher; title: Integration laboratory supplies; '
               'item: Sterile tubes; quantity: 4; unit price: $12.50; reason: Restock the laboratory')
    with TestClient(create_app(Settings(database_path=database_path))) as client:
        login(client, 'analyst')
        response = client.post('/api/v1/assistant/messages', json={'message': request})
        assert response.status_code == 200, response.text
        result = response.json()
        approval_id = result['answer']['approval_id']
        assert 'pending approval' in result['answer']['text']
        proposal_response = client.get(f'/api/v1/approvals/{approval_id}')
        assert proposal_response.status_code == 200
        proposal = proposal_response.json()
        req_id = proposal['subject_id']
        assert (proposal['approval_type'], proposal['status'], proposal['risk']) == ('requisition', 'pending', 'low')
        assert proposal['proposed']['supplier'] == 'Thermo Fisher'
        assert proposal['proposed']['lines'] == [{'description': 'Sterile tubes', 'quantity': 4, 'unit_price': '12.50'}]
        pending = detail(client, 'requisitions', req_id)
        assert (pending['item']['title'], pending['item']['status'], pending['item']['total_amount_usd']) == ('Integration laboratory supplies', 'pending_approval', '50.00')
        assert pending['relations']['lines'] == proposal['proposed']['lines']
        assert sign(client, approval_id).status_code == 403

        login(client, 'proc.manager')
        assert notification_for(client, approval_id)['body'] == 'A request is waiting for your review.'
        tables = ('requisitions', 'requisition_lines', 'approvals', 'signatures', 'notifications', 'audit_log')
        with closing(connect(database_path)) as db:
            before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
        denied = sign(client, approval_id, password='wrong')
        assert denied.status_code == 422
        with closing(connect(database_path)) as db:
            assert {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables} == before
        assert detail(client, 'requisitions', req_id)['item']['status'] == 'pending_approval'

        decision = sign(client, approval_id)
        assert decision.status_code == 200, decision.text
        assert decision.json()['status'] == 'approved'
        assert [(s['role'], s['meaning']) for s in decision.json()['signatures']] == [('procurement_manager', 'Approved')]
        approved = detail(client, 'requisitions', req_id)
        assert approved['item']['status'] == 'approved'
        assert approved['relations']['lines'] == pending['relations']['lines']
        audit = client.get('/api/v1/audit', params={'page_size': 100})
        assert audit.status_code == 200
        rows = audit.json()['items']
        for action in ('create_requisition', 'submit_requisition'):
            assert len([r for r in rows if r['action'] == action and r['record_type'] == 'requisition' and r['record_id'] == str(req_id)]) == 1
        signatures = [r for r in rows if r['action'] == 'sign' and r['record_type'] == 'approval' and r['record_id'] == str(approval_id)]
        assert len(signatures) == 1 and signatures[0]['role'] == 'procurement_manager'
        assert 'Demo@1234' not in signatures[0]['detail']
        login(client, 'analyst')
        assert notification_for(client, approval_id)['body'] == 'Your request was approved.'
        history = client.get(f"/api/v1/assistant/conversations/{result['conversation_id']}")
        assert history.status_code == 200
        assert history.json()['messages'][0]['content'] == request
        assert history.json()['messages'][1]['answer']['approval_id'] == approval_id


def change_state(path):
    """Capture proposal effects, excluding ordinary assistant query audit entries."""
    tables = ('suppliers', 'sourcing_events', 'sourcing_bids', 'approvals', 'signatures', 'notifications')
    with closing(connect(path)) as db:
        state = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
        state['audit_log'] = [tuple(row) for row in db.execute("SELECT * FROM audit_log WHERE action != 'query' ORDER BY rowid")]
        return state


@pytest.mark.parametrize('kind,account', [
    ('supplier_edit', 'category.mgr'),
    ('sourcing_create', 'sourcing'),
    ('sourcing_award', 'sourcing'),
])
def test_natural_change_journey_through_signatures(database_path, kind, account):
    """A natural proposal crosses assistant, approval, notification and record services."""
    with TestClient(create_app(Settings(database_path=database_path))) as client:
        login(client, account)
        if kind == 'supplier_edit':
            request = 'edit supplier Thermo Fisher; contact name: Integration Contact; risk: high'
            resource, subject_id, risk = 'suppliers', 1, 'high'
            original = detail(client, resource, subject_id)['item']
        elif kind == 'sourcing_create':
            request = 'create sourcing event; title: Integration Laboratory; type: RFP; value: 12000; end date: 2030-12-31'
            resource, subject_id, risk = 'sourcing', None, 'high'
            original = None
        else:
            resource, subject_id, risk = 'sourcing', 2, 'low'
            event = detail(client, resource, subject_id)
            original, bid = event['item'], event['relations']['bids'][0]
            request = f"award sourcing event {original['code']}; bid: {bid['id']}"

        response = client.post('/api/v1/assistant/messages', json={'message': request})
        assert response.status_code == 200, response.text
        result = response.json()
        approval_id = result['answer']['approval_id']
        approval_response = client.get(f'/api/v1/approvals/{approval_id}')
        assert approval_response.status_code == 200
        proposal = approval_response.json()
        subject_id = proposal['subject_id']
        assert (proposal['approval_type'], proposal['status'], proposal['risk']) == (kind, 'pending', risk)
        pending = detail(client, resource, subject_id)['item']
        if kind == 'supplier_edit':
            assert proposal['current'] == {'contact_name': original['contact_name'], 'risk': original['risk']}
            assert proposal['proposed'] == {'contact_name': 'Integration Contact', 'risk': 'high'}
            assert (pending['contact_name'], pending['risk']) == (original['contact_name'], original['risk'])
        elif kind == 'sourcing_create':
            assert proposal['current'] == {}
            assert (pending['title'], pending['event_type'], pending['status']) == ('Integration Laboratory', 'RFP', 'pending_approval')
            assert (pending['estimated_value_usd'], pending['end_date']) == ('12000', '2030-12-31')
        else:
            assert proposal['proposed']['bid_id'] == bid['id']
            assert proposal['proposed']['winning_supplier_id'] == bid['supplier_id']
            assert (pending['status'], pending['winning_supplier_id']) == ('active', None)

        before_denial = change_state(database_path)
        assert sign(client, approval_id).status_code == 403
        assert change_state(database_path) == before_denial
        login(client, 'proc.manager')
        assert notification_for(client, approval_id)['body'] == 'A request is waiting for your review.'
        before_bad_password = change_state(database_path)
        assert sign(client, approval_id, password='wrong').status_code == 422
        assert change_state(database_path) == before_bad_password
        first = sign(client, approval_id)
        assert first.status_code == 200, first.text
        assert first.json()['status'] == ('pending_second' if risk == 'high' else 'approved')
        assert [(s['role'], s['meaning']) for s in first.json()['signatures']] == [('procurement_manager', 'Approved')]
        if risk == 'high':
            assert detail(client, resource, subject_id)['item'] == pending
            login(client, 'compliance')
            assert notification_for(client, approval_id)['body'] == 'A request is waiting for your review.'
            final = sign(client, approval_id)
            assert final.status_code == 200, final.text
            assert final.json()['status'] == 'approved'
            assert [(s['role'], s['meaning']) for s in final.json()['signatures']] == [
                ('procurement_manager', 'Approved'), ('compliance', 'Approved')]

        applied = detail(client, resource, subject_id)['item']
        if kind == 'supplier_edit':
            assert (applied['contact_name'], applied['risk']) == ('Integration Contact', 'high')
        elif kind == 'sourcing_create':
            assert (applied['title'], applied['status']) == ('Integration Laboratory', 'active')
        else:
            assert (applied['status'], applied['winning_supplier_id']) == ('awarded', bid['supplier_id'])

        login(client, 'proc.manager')
        audit = client.get('/api/v1/audit', params={'page_size': 100})
        assert audit.status_code == 200
        rows = audit.json()['items']
        action = {'supplier_edit': 'propose_supplier_edit', 'sourcing_create': 'create_sourcing_event', 'sourcing_award': 'request_award'}[kind]
        table = 'suppliers' if kind == 'supplier_edit' else 'sourcing_events'
        assert len([r for r in rows if r['action'] == action and r['record_type'] == table and r['record_id'] == str(subject_id)]) == 1
        signed = [r for r in rows if r['action'] == 'sign' and r['record_type'] == 'approval' and r['record_id'] == str(approval_id)]
        assert {r['role'] for r in signed} == ({'procurement_manager', 'compliance'} if risk == 'high' else {'procurement_manager'})
        assert len(signed) == (2 if risk == 'high' else 1)
        assert all('Demo@1234' not in row['detail'] for row in signed)
        login(client, account)
        assert notification_for(client, approval_id)['body'] == 'Your request was approved.'
        history = client.get(f"/api/v1/assistant/conversations/{result['conversation_id']}")
        assert history.status_code == 200
        assert history.json()['messages'][0]['content'] == request
        assert history.json()['messages'][1]['answer']['approval_id'] == approval_id
        with closing(connect(database_path)) as db:
            assert db.execute('SELECT status FROM approvals WHERE id=?', (approval_id,)).fetchone()[0] == 'approved'
            assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?', (approval_id,)).fetchone()[0] == (2 if risk == 'high' else 1)
            if kind == 'supplier_edit':
                assert tuple(db.execute('SELECT contact_name,risk FROM suppliers WHERE id=?', (subject_id,)).fetchone()) == ('Integration Contact', 'high')
            else:
                expected = ('active', None) if kind == 'sourcing_create' else ('awarded', bid['supplier_id'])
                assert tuple(db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=?', (subject_id,)).fetchone()) == expected


@pytest.mark.parametrize('account,question,expected', [
    ('finance', 'edit supplier Thermo Fisher; risk: high', 'not permitted'),
    ('finance', 'create sourcing event; title: Lab; type: RFQ; value: 5000; end date: 2030-12-31', 'not permitted'),
    ('finance', 'award sourcing event SE-3002; bid: 3', 'not permitted'),
    ('category.mgr', 'edit supplier Thermo Fisher; risk: extreme', 'no change has been made'),
    ('sourcing', 'create sourcing event; title: Lab; type: RFQ; value: 5000; end date: 2030-02-30', 'no change has been made'),
    ('sourcing', 'award sourcing event SE-3002; bid: 1', 'no change has been made'),
])
def test_natural_change_denials_have_no_proposal_effects(database_path, account, question, expected):
    """Clarifications may persist a conversation, but never a proposal or decision."""
    with TestClient(create_app(Settings(database_path=database_path))) as client:
        login(client, account)
        before = change_state(database_path)
        response = client.post('/api/v1/assistant/messages', json={'message': question})
        assert response.status_code == 200, response.text
        assert expected in response.json()['answer']['text'].lower()
        assert not response.json()['answer'].get('approval_id')
        assert change_state(database_path) == before


def test_unauthorized_and_invalid_cross_feature_requests_do_not_create_changes(database_path):
    with TestClient(create_app(Settings(database_path=database_path))) as client:
        action = {'kind': 'sourcing_award', 'event_id': 2, 'details': {'bid_id': 3}}
        assert message(client, 'Award this event', action).status_code == 401
        login(client, 'finance')
        with closing(connect(database_path)) as db:
            before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')]
                      for table in ('sourcing_events', 'approvals', 'signatures', 'notifications')}
        denied = message(client, 'Award this event', action)
        assert denied.status_code == 200 and 'not permitted' in denied.json()['answer']['text']
        assert 'approval_id' not in denied.json()['answer']
        assert client.post('/api/v1/sourcing/2/awards', json={'bid_id': 3}).status_code == 403
        login(client, 'sourcing')
        # Bid 1 belongs to event 1, not event 2; no approval or notification may leak.
        invalid = message(client, 'Award this event', {
            'kind': 'sourcing_award', 'event_id': 2, 'details': {'bid_id': 1},
        })
        assert invalid.status_code == 422
        assert message(client, 'Award missing event', {
            'kind': 'sourcing_award', 'event_id': 9999, 'details': {'bid_id': 3},
        }).status_code == 404
        with closing(connect(database_path)) as db:
            after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in before}
            assert after == before



@pytest.mark.parametrize('operation', ['reset', 'deactivate'])
def test_account_revocation_blocks_records_and_assistant_without_changing_data(database_path, operation):
    """An admin action invalidates an authenticated user's cross-feature access."""
    with TestClient(create_app(Settings(database_path=database_path))) as admin:
        assert admin.post('/api/v1/auth/login', json={'email': 'admin@procurem.demo', 'password': 'Admin@5678'}).status_code == 200
        created = admin.post('/api/v1/users', json={'email': 'isolated@example.com', 'display_name': 'Isolated Analyst', 'role': 'analyst'})
        assert created.status_code == 201
        account = created.json()
        uid, password = account['user']['id'], account['temporary_password']
        with TestClient(admin.app) as user:
            assert user.post('/api/v1/auth/login', json={'email': 'isolated@example.com', 'password': password}).status_code == 200
            assert user.get('/api/v1/records/suppliers/1').status_code == 200
            answer = message(user, 'show suppliers', None)
            assert answer.status_code == 200
            conversation_id = answer.json()['conversation_id']
            if operation == 'reset':
                result = admin.post(f'/api/v1/users/{uid}/reset-password')
                assert result.status_code == 200
                new_password = result.json()['temporary_password']
            else:
                result = admin.put(f'/api/v1/users/{uid}', json={'display_name': 'Isolated Analyst', 'role': 'analyst', 'status': 'inactive'})
                assert result.status_code == 200 and result.json()['status'] == 'inactive'
            tables = ('suppliers', 'requisitions', 'approvals', 'notifications', 'conversations', 'messages', 'audit_log')
            with closing(connect(database_path)) as db:
                before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
                assert db.execute('SELECT count(*) FROM sessions WHERE user_id=? AND revoked_at IS NULL', (uid,)).fetchone()[0] == 0
            assert user.get('/api/v1/records/suppliers').status_code == 401
            assert user.get('/api/v1/records/suppliers/1').status_code == 401
            assert user.get(f'/api/v1/assistant/conversations/{conversation_id}').status_code == 401
            assert message(user, 'Create a requisition', {'kind': 'requisition', 'details': {'supplier_id': 1, 'title': 'Denied', 'reason': 'Denied', 'lines': [{'description': 'Vials', 'quantity': 1, 'unit_price': '1.00'}]}}).status_code == 401
            with closing(connect(database_path)) as db:
                after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
                assert after == before
            assert user.post('/api/v1/auth/login', json={'email': 'isolated@example.com', 'password': password}).status_code == 401
            if operation == 'reset':
                assert user.post('/api/v1/auth/login', json={'email': 'isolated@example.com', 'password': new_password}).status_code == 200
                assert user.get('/api/v1/records/suppliers/1').status_code == 200
                assert user.get(f'/api/v1/assistant/conversations/{conversation_id}').status_code == 200
