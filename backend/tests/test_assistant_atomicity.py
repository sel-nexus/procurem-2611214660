"""Verify assistant proposals and their conversation turns commit together."""
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import connect
from app.main import create_app
from app.schemas.assistant import MessageInput
from app.services import assistant


@pytest.fixture
def workspace():
    """Start a seeded application with an isolated file-backed database."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'atomicity.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path


@pytest.fixture(params=['requisition', 'supplier_edit', 'sourcing_create', 'sourcing_award'])
def proposal(request, workspace):
    """Prepare a valid action for each supported proposal type."""
    client, path = workspace
    kind = request.param
    account = 'analyst' if kind == 'requisition' else 'sourcing'
    assert client.post('/api/v1/auth/login', json={'email': f'{account}@procurem.demo', 'password': 'Demo@1234'}).status_code == 200
    if kind == 'requisition':
        action = {'kind': kind, 'details': {'supplier_id': 1, 'title': 'Atomic requisition', 'reason': 'Needed', 'lines': [{'description': 'Tubes', 'quantity': 2, 'unit_price': '5.00'}]}}
    elif kind == 'supplier_edit':
        action = {'kind': kind, 'supplier_id': 1, 'details': {'contact_name': 'Atomic contact'}}
    elif kind == 'sourcing_create':
        action = {'kind': kind, 'details': {'title': 'Atomic RFQ', 'event_type': 'RFQ', 'estimated_value_usd': '100.00', 'end_date': '2028-01-01'}}
    else:
        with connect(path) as db:
            event = db.execute("SELECT id FROM sourcing_events WHERE status='active' AND id != 1 LIMIT 1").fetchone()[0]
            bid = db.execute('SELECT id FROM sourcing_bids WHERE event_id=? LIMIT 1', (event,)).fetchone()[0]
        action = {'kind': kind, 'event_id': event, 'details': {'bid_id': bid}}
    return action


TABLES = ('requisitions', 'requisition_lines', 'suppliers', 'sourcing_events', 'approvals', 'notifications', 'audit_log', 'conversations', 'messages')


def snapshot(path):
    """Read durable rows through a separate database connection."""
    with connect(path) as db:
        return {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in TABLES}


@pytest.mark.parametrize('failure', ['assistant_message', 'query_audit', 'notification'])
@pytest.mark.parametrize('existing', [False, True])
def test_action_failure_rolls_back_all_rows(workspace, proposal, failure, existing):
    client, path = workspace
    conversation_id = None
    if existing:
        response = client.post('/api/v1/assistant/messages', json={'message': 'hello'})
        assert response.status_code == 200
        conversation_id = response.json()['conversation_id']
    triggers = {
        'assistant_message': "CREATE TRIGGER fail_turn BEFORE INSERT ON messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'injected failure'); END",
        'query_audit': "CREATE TRIGGER fail_turn BEFORE INSERT ON audit_log WHEN NEW.action='query' BEGIN SELECT RAISE(ABORT, 'injected failure'); END",
        'notification': "CREATE TRIGGER fail_turn BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT, 'injected failure'); END",
    }
    with connect(path) as db:
        db.execute(triggers[failure])
    before = snapshot(path)
    with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
        client.post('/api/v1/assistant/messages', json={'message': 'submit proposal', 'conversation_id': conversation_id, 'action': proposal})
    assert snapshot(path) == before


def test_action_failure_rolls_back_on_reusable_connection(workspace, proposal):
    _, path = workspace
    account = 'analyst' if proposal['kind'] == 'requisition' else 'sourcing'
    with connect(path) as setup:
        setup.execute("CREATE TRIGGER fail_query BEFORE INSERT ON audit_log WHEN NEW.action='query' BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    before = snapshot(path)
    with connect(path) as db:
        user = db.execute('SELECT * FROM users WHERE email=?', (f'{account}@procurem.demo',)).fetchone()
        body = MessageInput.model_validate({'message': 'submit proposal', 'action': proposal})
        with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
            assistant.send(db, user, body)
        assert not db.in_transaction
        assert snapshot(path) == before
        db.execute('DROP TRIGGER fail_query')
        result = assistant.send(db, user, body)
        assert not db.in_transaction
    with connect(path) as db:
        assert db.execute('SELECT status FROM approvals WHERE id=?', (result['answer']['approval_id'],)).fetchone()[0] == 'pending'


@pytest.mark.parametrize('existing', [False, True])
def test_action_success_persists_approval_turn_audits_and_notification(workspace, proposal, existing):
    client, path = workspace
    conversation_id = None
    if existing:
        response = client.post('/api/v1/assistant/messages', json={'message': 'hello'})
        assert response.status_code == 200
        conversation_id = response.json()['conversation_id']
    before = snapshot(path)
    response = client.post('/api/v1/assistant/messages', json={'message': 'submit proposal', 'conversation_id': conversation_id, 'action': proposal})
    assert response.status_code == 200
    result = response.json()
    if existing:
        assert result['conversation_id'] == conversation_id
    aid = result['answer']['approval_id']
    with connect(path) as db:
        approval = db.execute('SELECT * FROM approvals WHERE id=?', (aid,)).fetchone()
        assert approval['approval_type'] == proposal['kind'] and approval['status'] == 'pending'
        messages = db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY id', (result['conversation_id'],)).fetchall()
        assert [row['role'] for row in messages[-2:]] == ['user', 'assistant']
        assert messages[-2]['content'] == 'submit proposal'
        assert json.loads(messages[-1]['content']) == result['answer']
        assert messages[-1]['id'] == result['message_id']
        assert db.execute('SELECT count(*) FROM notifications WHERE link=?', (f'/approvals/{aid}',)).fetchone()[0] >= 1
        assert db.execute("SELECT count(*) FROM audit_log WHERE action='query' AND record_id=?", (str(result['conversation_id']),)).fetchone()[0] >= 1
        if proposal['kind'] == 'requisition':
            assert db.execute('SELECT status FROM requisitions WHERE id=?', (approval['subject_id'],)).fetchone()[0] == 'pending_approval'
            assert db.execute('SELECT count(*) FROM requisition_lines WHERE requisition_id=?', (approval['subject_id'],)).fetchone()[0] == 1
        elif proposal['kind'] == 'sourcing_create':
            assert db.execute('SELECT status FROM sourcing_events WHERE id=?', (approval['subject_id'],)).fetchone()[0] == 'pending_approval'
        else:
            assert snapshot(path)['suppliers' if proposal['kind'] == 'supplier_edit' else 'sourcing_events'] == before['suppliers' if proposal['kind'] == 'supplier_edit' else 'sourcing_events']
    after = snapshot(path)
    assert len(after['approvals']) == len(before['approvals']) + 1
    assert len(after['messages']) == len(before['messages']) + 2
    assert len(after['audit_log']) == len(before['audit_log']) + (3 if proposal['kind'] == 'requisition' else 2)
    assert len(after['conversations']) == len(before['conversations']) + (0 if existing else 1)
