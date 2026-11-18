"""Exercise assistant intent, context, proposal and authorization branches."""
import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import connect
from app.main import create_app


@pytest.fixture
def workspace():
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'assistant-branches.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path


def login(client, name):
    response = client.post('/api/v1/auth/login', json={'email': f'{name}@procurem.demo', 'password': 'Demo@1234'})
    assert response.status_code == 200


def send(client, text, conversation_id=None, action=None):
    return client.post('/api/v1/assistant/messages', json={'message': text, 'conversation_id': conversation_id, 'action': action})


def test_intent_filters_context_ambiguity_and_persisted_history(workspace):
    client, path = workspace
    login(client, 'analyst')
    first = send(client, 'Thermo Fisher catalog and contracts')
    assert first.status_code == 200
    body = first.json()
    sections = body['answer']['sections']
    assert [s['resource'] for s in sections] == ['suppliers', 'catalog', 'contracts']
    assert sections[0]['rows'][0]['name'] == 'Thermo Fisher'
    assert all(row['supplier_name'] == 'Thermo Fisher' for s in sections[1:] for row in s['rows'])
    cid = body['conversation_id']
    followup = send(client, 'their requisitions', cid).json()['answer']
    assert followup['sections'][0]['resource'] == 'requisitions'
    assert all(row['supplier_name'] == 'Thermo Fisher' for row in followup['sections'][0]['rows'])
    assert send(client, 'their orders', cid).json()['answer']['text'] == 'Which supplier do you mean?'
    with connect(path) as db:
        names = [row['name'] for row in db.execute('SELECT name FROM suppliers ORDER BY id LIMIT 2')]
    ambiguous = send(client, f'{names[0]} and {names[1]} orders').json()['answer']
    assert ambiguous['text'] == 'Which supplier do you mean?' and not ambiguous['sections']
    assert send(client, 'hello').json()['answer']['text'].startswith('I can answer questions')
    history = client.get(f'/api/v1/assistant/conversations/{cid}').json()['messages']
    assert [message['role'] for message in history] == ['user', 'assistant'] * 3
    assert history[1]['answer']['sections'] == sections
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM messages WHERE conversation_id=?', (cid,)).fetchone()[0] == 6


def test_intent_queries_knowledge_csv_safety_and_missing_answer(workspace):
    client, path = workspace
    login(client, 'analyst')
    with connect(path) as db:
        db.execute("UPDATE suppliers SET name='=SUM(1,2)' WHERE id=1")
    result = send(client, 'suppliers').json()
    url = f"/api/v1/assistant/conversations/{result['conversation_id']}/messages/{result['message_id']}/csv"
    rows = list(csv.DictReader(io.StringIO(client.get(url).text)))
    assert any(row['name'] == "'=SUM(1,2)" for row in rows)
    assert client.get(url.replace(f"/{result['message_id']}/csv", '/999999/csv')).status_code == 404
    knowledge = send(client, 'knowledge about zzzunlikelyword').json()['answer']
    assert knowledge['sections'][0]['resource'] == 'knowledge'
    assert knowledge['sections'][0]['rows'] == []
    assert 'No matching records' in knowledge['text']
    orders = send(client, 'open orders without invoice').json()['answer']['sections'][0]['rows']
    assert orders and all(row['status'] == 'open' and not row['has_invoice'] for row in orders)


def test_sourcing_actions_pending_role_denial_and_invalid_bid_are_atomic(workspace):
    client, path = workspace
    create = {'kind': 'sourcing_create', 'details': {'title': 'Assistant RFQ', 'event_type': 'RFQ', 'estimated_value_usd': '123.00', 'end_date': '2028-01-01'}}
    login(client, 'finance')
    denied = send(client, 'create sourcing event', action=create)
    assert denied.status_code == 200 and 'not permitted' in denied.json()['answer']['text']
    with connect(path) as db:
        before = db.execute('SELECT count(*) FROM sourcing_events').fetchone()[0]
        approvals_before = db.execute('SELECT count(*) FROM approvals').fetchone()[0]
    login(client, 'sourcing')
    created = send(client, 'create sourcing event', action=create)
    assert created.status_code == 200
    aid = created.json()['answer']['approval_id']
    with connect(path) as db:
        approval = db.execute('SELECT status,subject_id,requester_id FROM approvals WHERE id=?', (aid,)).fetchone()
        assert approval['status'] == 'pending'
        assert db.execute('SELECT title,status FROM sourcing_events WHERE id=?', (approval['subject_id'],)).fetchone()[:] == ('Assistant RFQ', 'pending_approval')
        assert db.execute('SELECT count(*) FROM sourcing_events').fetchone()[0] == before + 1
        assert db.execute('SELECT count(*) FROM approvals').fetchone()[0] == approvals_before + 1
        event = db.execute("SELECT id FROM sourcing_events WHERE status='active' AND id != 1 LIMIT 1").fetchone()[0]
        bid = db.execute('SELECT id FROM sourcing_bids WHERE event_id=? LIMIT 1', (event,)).fetchone()[0]
        wrong_bid = db.execute('SELECT id FROM sourcing_bids WHERE event_id != ? LIMIT 1', (event,)).fetchone()[0]
    bad = send(client, 'award event', action={'kind': 'sourcing_award', 'event_id': event, 'details': {'bid_id': wrong_bid}})
    assert bad.status_code == 422
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM approvals').fetchone()[0] == approvals_before + 1
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=?', (event,)).fetchone()[:] == ('active', None)
    good = send(client, 'award event', action={'kind': 'sourcing_award', 'event_id': event, 'details': {'bid_id': bid}})
    assert good.status_code == 200
    award_id = good.json()['answer']['approval_id']
    with connect(path) as db:
        assert db.execute('SELECT approval_type,status,subject_id FROM approvals WHERE id=?', (award_id,)).fetchone()[:] == ('sourcing_award', 'pending', event)
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=?', (event,)).fetchone()[:] == ('active', None)
        assert db.execute('SELECT count(*) FROM notifications WHERE link=?', (f'/approvals/{award_id}',)).fetchone()[0] == 1


def test_requisition_invalid_supplier_rolls_back_and_unauthorized_conversation_is_hidden(workspace):
    client, path = workspace
    login(client, 'analyst')
    with connect(path) as db:
        before = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('requisitions', 'requisition_lines', 'approvals', 'messages')]
    action = {'kind': 'requisition', 'details': {'supplier_id': 999999, 'title': 'Needed', 'reason': 'Research', 'lines': [{'description': 'Tubes', 'quantity': 2, 'unit_price': '5.00'}]}}
    failed = send(client, 'create requisition', action=action)
    assert failed.status_code == 422
    with connect(path) as db:
        after = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('requisitions', 'requisition_lines', 'approvals', 'messages')]
    assert after == before
    thread = send(client, 'contracts').json()
    login(client, 'finance')
    assert send(client, 'invoices', thread['conversation_id']).status_code == 404
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM messages WHERE conversation_id=?', (thread['conversation_id'],)).fetchone()[0] == 2
