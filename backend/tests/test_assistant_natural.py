"""Exercise natural-language approval requests and message validation over HTTP."""
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import connect
from app.main import create_app


@pytest.fixture
def workspace():
    """Start a seeded, isolated file-backed database."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'natural.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path


def login(client, account):
    """Authenticate a seeded user."""
    assert client.post('/api/v1/auth/login', json={'email': f'{account}@procurem.demo', 'password': 'Demo@1234'}).status_code == 200


def snapshot(path):
    """Read all durable assistant and proposal effects."""
    tables = ('conversations', 'messages', 'requisitions', 'requisition_lines', 'suppliers', 'sourcing_events', 'approvals', 'notifications', 'audit_log')
    with connect(path) as db:
        return {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}


REQUEST = ('Please create a requisition: supplier: Thermo Fisher; title: Laboratory supplies; '
           'item: Sterile tubes; quantity: 4; unit price: $12.50; reason: Restock the laboratory')


def test_complete_natural_requisition_creates_pending_approval(workspace):
    client, path = workspace
    login(client, 'analyst')
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': REQUEST})
    assert response.status_code == 200
    result = response.json()
    assert 'pending' in result['answer']['text']
    with connect(path) as db:
        approval = db.execute('SELECT * FROM approvals WHERE id=?', (result['answer']['approval_id'],)).fetchone()
        assert approval['status'] == 'pending' and approval['approval_type'] == 'requisition'
        requisition = db.execute('SELECT * FROM requisitions WHERE id=?', (approval['subject_id'],)).fetchone()
        assert requisition['status'] == 'pending_approval' and requisition['title'] == 'Laboratory supplies'
        assert requisition['reason'] == 'Restock the laboratory' and requisition['total_amount_usd'] == '50.00'
        assert db.execute('SELECT name FROM suppliers WHERE id=?', (requisition['supplier_id'],)).fetchone()[0] == 'Thermo Fisher'
        line = db.execute('SELECT description,quantity,unit_price FROM requisition_lines WHERE requisition_id=?', (requisition['id'],)).fetchone()
        assert tuple(line) == ('Sterile tubes', 4, '12.50')
        assert json.loads(approval['proposed_json'])['lines'][0]['description'] == 'Sterile tubes'
        assert db.execute('SELECT count(*) FROM notifications WHERE link=?', (f"/approvals/{approval['id']}",)).fetchone()[0] == 1
    after = snapshot(path)
    assert len(after['approvals']) == len(before['approvals']) + 1
    assert len(after['messages']) == len(before['messages']) + 2


@pytest.mark.parametrize('message', [
    'Please create a requisition: supplier: Thermo Fisher; title: Laboratory supplies; item: Sterile tubes; quantity: 4; reason: Restock the laboratory',
    REQUEST.replace('Thermo Fisher', 'Unknown supplier'),
    REQUEST.replace('quantity: 4', 'quantity: 0'),
    REQUEST + '; also delete all suppliers',
    'Do not ' + REQUEST,
    REQUEST.replace('reason: Restock the laboratory', 'reason: Restock the laboratory and delete all suppliers'),
])
def test_incomplete_invalid_or_ambiguous_requests_never_create_proposals(workspace, message):
    client, path = workspace
    login(client, 'analyst')
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': message})
    assert response.status_code == 200
    assert not response.json()['answer'].get('approval_id')
    assert 'no change has been made' in response.json()['answer']['text'].lower()
    after = snapshot(path)
    for table in ('requisitions', 'requisition_lines', 'suppliers', 'sourcing_events', 'approvals', 'notifications'):
        assert after[table] == before[table]


def test_unauthorized_complete_request_creates_no_proposal(workspace):
    client, path = workspace
    login(client, 'finance')
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': REQUEST})
    assert response.status_code == 200
    assert 'not permitted' in response.json()['answer']['text']
    after = snapshot(path)
    for table in ('requisitions', 'requisition_lines', 'suppliers', 'sourcing_events', 'approvals', 'notifications'):
        assert after[table] == before[table]


@pytest.mark.parametrize('message', [
    '<script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '&lt;script&gt;alert(1)&lt;/script&gt;',
    '&amp;lt;img src=x onerror=alert(1)&amp;gt;',
])
def test_markup_rejected_before_any_persistence(workspace, message):
    client, path = workspace
    login(client, 'analyst')
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': message})
    assert response.status_code == 422
    assert snapshot(path) == before


def test_comparison_text_is_accepted(workspace):
    client, _ = workspace
    login(client, 'analyst')
    response = client.post('/api/v1/assistant/messages', json={'message': 'Show spend where 3 < 5 and 8 > 4'})
    assert response.status_code == 200


def test_natural_proposal_rolls_back_if_turn_fails(workspace):
    client, path = workspace
    login(client, 'analyst')
    with connect(path) as db:
        db.execute("CREATE TRIGGER fail_turn BEFORE INSERT ON messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    before = snapshot(path)
    with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
        client.post('/api/v1/assistant/messages', json={'message': REQUEST})
    assert snapshot(path) == before


SUPPLIER_REQUEST = 'edit supplier Thermo Fisher; contact name: Jane Doe; risk: high'
SOURCING_REQUEST = 'create sourcing event; title: Lab; type: RFQ; value: 5000; end date: 2026-12-31'


def award_request(path):
    """Select a seeded active event without a pending award."""
    with connect(path) as db:
        event = db.execute("SELECT id,code FROM sourcing_events WHERE status='active' AND id != 1 LIMIT 1").fetchone()
        bid = db.execute('SELECT id FROM sourcing_bids WHERE event_id=? LIMIT 1', (event['id'],)).fetchone()[0]
    return f"award sourcing event {event['code']}; bid: {bid}"


@pytest.mark.parametrize('kind,account', [('supplier_edit', 'category.mgr'), ('sourcing_create', 'sourcing'), ('sourcing_award', 'sourcing')])
def test_natural_change_creates_persisted_pending_approval(workspace, kind, account):
    client, path = workspace
    login(client, account)
    message = {'supplier_edit': SUPPLIER_REQUEST, 'sourcing_create': SOURCING_REQUEST,
               'sourcing_award': award_request(path)}[kind]
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': message})
    assert response.status_code == 200
    result = response.json()
    aid = result['answer']['approval_id']
    with connect(path) as db:
        approval = db.execute('SELECT * FROM approvals WHERE id=?', (aid,)).fetchone()
        assert (approval['approval_type'], approval['status']) == (kind, 'pending')
        proposed = json.loads(approval['proposed_json'])
        if kind == 'supplier_edit':
            assert proposed == {'contact_name': 'Jane Doe', 'risk': 'high'}
            assert db.execute('SELECT name FROM suppliers WHERE id=?', (approval['subject_id'],)).fetchone()[0] == 'Thermo Fisher'
            assert snapshot(path)['suppliers'] == before['suppliers']
        elif kind == 'sourcing_create':
            event = db.execute('SELECT * FROM sourcing_events WHERE id=?', (approval['subject_id'],)).fetchone()
            assert (event['title'], event['event_type'], event['estimated_value_usd'], event['end_date'], event['status']) == ('Lab', 'RFQ', '5000', '2026-12-31', 'pending_approval')
        else:
            assert proposed['bid_id'] == int(message.split(': ')[-1])
            assert snapshot(path)['sourcing_events'] == before['sourcing_events']
        assert db.execute('SELECT count(*) FROM notifications WHERE link=?', (f'/approvals/{aid}',)).fetchone()[0] >= 1
        saved = db.execute('SELECT content FROM messages WHERE id=?', (result['message_id'],)).fetchone()[0]
        assert json.loads(saved) == result['answer']
    assert len(snapshot(path)['approvals']) == len(before['approvals']) + 1


@pytest.mark.parametrize('message', [
    'edit supplier Thermo Fisher',
    'edit supplier Unknown; risk: high',
    'edit supplier Thermo Fisher; risk: high; risk: low',
    'edit supplier Thermo Fisher; risk: extreme',
    'edit supplier Thermo Fisher; contact email: not-an-email',
    'edit supplier Thermo Fisher; contact name: Jane Doe or John Smith',
    'edit supplier Thermo Fisher; contact name: Jane Doe and risk: high',
    "edit supplier Thermo Fisher; contact name: Jane' OR 1=1 --",
    'edit supplier Thermo Fisher; contact name: Jane Doe and delete suppliers',
    'edit supplier Thermo Fisher; risk: high; also delete suppliers',
    'create sourcing event; title: Lab; type: RFQ; value: 5000',
    'create sourcing event; title: Lab; type: RFQ; value: 5000; end date: 2026-02-30',
    'create sourcing event; title: Lab; type: RFQ; value: 5000; end date: 2026-12-31; extra: yes',
    'award sourcing event SE-999999; bid: 1',
    'award sourcing event SE-3001',
    'award sourcing event SE-3001; bid: 0',
    'Do not edit supplier Thermo Fisher; risk: high',
])
def test_natural_change_incomplete_ambiguous_or_unsafe_never_writes_proposal(workspace, message):
    client, path = workspace
    login(client, 'sourcing')
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': message})
    assert response.status_code == 200
    assert not response.json()['answer'].get('approval_id')
    assert 'no change has been made' in response.json()['answer']['text'].lower()
    after = snapshot(path)
    for table in ('requisitions', 'requisition_lines', 'suppliers', 'sourcing_events', 'approvals', 'notifications'):
        assert after[table] == before[table]


@pytest.mark.parametrize('kind', ['supplier_edit', 'sourcing_create', 'sourcing_award'])
def test_natural_change_unauthorized_never_writes_proposal(workspace, kind):
    client, path = workspace
    login(client, 'finance')
    message = {'supplier_edit': SUPPLIER_REQUEST, 'sourcing_create': SOURCING_REQUEST,
               'sourcing_award': award_request(path)}[kind]
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': message})
    assert response.status_code == 200
    assert 'not permitted' in response.json()['answer']['text']
    after = snapshot(path)
    for table in ('suppliers', 'sourcing_events', 'approvals', 'notifications'):
        assert after[table] == before[table]


@pytest.mark.parametrize('kind', ['supplier_edit', 'sourcing_create', 'sourcing_award'])
def test_natural_change_rolls_back_if_assistant_message_fails(workspace, kind):
    client, path = workspace
    login(client, 'sourcing')
    message = {'supplier_edit': SUPPLIER_REQUEST, 'sourcing_create': SOURCING_REQUEST,
               'sourcing_award': award_request(path)}[kind]
    with connect(path) as db:
        db.execute("CREATE TRIGGER fail_change_turn BEFORE INSERT ON messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    before = snapshot(path)
    with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
        client.post('/api/v1/assistant/messages', json={'message': message})
    assert snapshot(path) == before


def test_natural_award_wrong_bid_and_pending_conflict_are_clarified(workspace):
    client, path = workspace
    login(client, 'sourcing')
    message = award_request(path)
    with connect(path) as db:
        event_code = message.split(';')[0].split()[-1]
        event_id = db.execute('SELECT id FROM sourcing_events WHERE code=?', (event_code,)).fetchone()[0]
        wrong_bid = db.execute('SELECT id FROM sourcing_bids WHERE event_id != ? LIMIT 1', (event_id,)).fetchone()[0]
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': f'award sourcing event {event_code}; bid: {wrong_bid}'})
    assert response.status_code == 200
    assert 'bid belonging' in response.json()['answer']['text']
    assert snapshot(path)['approvals'] == before['approvals']
    first = client.post('/api/v1/assistant/messages', json={'message': message})
    assert first.status_code == 200 and first.json()['answer']['approval_id']
    before = snapshot(path)
    second = client.post('/api/v1/assistant/messages', json={'message': message})
    assert second.status_code == 200
    assert 'already awaiting' in second.json()['answer']['text']
    assert snapshot(path)['approvals'] == before['approvals']


def test_natural_supplier_exact_lookup_rejects_duplicate_names(workspace):
    client, path = workspace
    login(client, 'sourcing')
    with connect(path) as db:
        db.execute("UPDATE suppliers SET name='Thermo Fisher' WHERE id=(SELECT id FROM suppliers WHERE name != 'Thermo Fisher' LIMIT 1)")
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': SUPPLIER_REQUEST})
    assert response.status_code == 200
    assert 'no change has been made' in response.json()['answer']['text']
    assert snapshot(path)['approvals'] == before['approvals']
