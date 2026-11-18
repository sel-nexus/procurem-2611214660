"""Exercise grounded answers and ownership against persistent SQLite."""
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
    """Start a fresh seeded application on a file database."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'assistant.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path


def login(client, name):
    """Sign in as a seeded user."""
    response = client.post('/api/v1/auth/login', json={'email':f'{name}@procurem.demo','password':'Demo@1234'})
    assert response.status_code == 200


def send(client, text, conversation_id=None, action=None):
    """Send one message through the public API."""
    return client.post('/api/v1/assistant/messages', json={'message':text,'conversation_id':conversation_id,'action':action})


def test_overdue_csv_and_persistence(workspace):
    client,path = workspace
    assert send(client,'orders').status_code == 401
    login(client,'analyst')
    response = send(client,'which purchase orders are overdue')
    assert response.status_code == 200
    result = response.json()
    section = result['answer']['sections'][0]
    assert section['table'] == 'purchase_orders' and section['rows']
    assert all(row['status'] == 'overdue' for row in section['rows'])
    assert {x['code'] for x in section['citations']} == {x['code'] for x in section['rows']}
    assert section['source'] == 'Mock · Oracle' and section['freshness'] == 'Real-time'
    url = f"/api/v1/assistant/conversations/{result['conversation_id']}/messages/{result['message_id']}/csv"
    csv_response = client.get(url)
    assert csv_response.status_code == 200
    assert csv_response.headers['content-type'].startswith('text/csv')
    exported = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert {x['code'] for x in exported} == {x['code'] for x in section['rows']}
    assert all(x['status'] == 'overdue' for x in exported)
    history = client.get(f"/api/v1/assistant/conversations/{result['conversation_id']}")
    assert history.status_code == 200 and history.json()['messages'][1]['answer'] == result['answer']
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM audit_log WHERE action='query'").fetchone()[0] == 1


def test_multi_intent_followup_clarification_and_no_match(workspace):
    client,path = workspace
    login(client,'analyst')
    response = send(client,'Thermo Fisher open orders and spend')
    assert response.status_code == 200
    result = response.json()
    sections = result['answer']['sections']
    assert [s['table'] for s in sections] == ['suppliers','purchase_orders','spend_monthly']
    assert sections[0]['rows'][0]['name'] == 'Thermo Fisher'
    assert all(x['status'] == 'open' and x['supplier_name'] == 'Thermo Fisher' for x in sections[1]['rows'])
    assert all(x['supplier_name'] == 'Thermo Fisher' and x['year'] == 2026 for x in sections[2]['rows'])
    assert 'FY2026' in result['answer']['text']
    cid = result['conversation_id']
    response = send(client,'their open orders',cid).json()['answer']
    assert all(x['supplier_name'] == 'Thermo Fisher' for x in response['sections'][0]['rows'])
    ambiguous = send(client,'status',cid).json()['answer']
    assert not ambiguous['sections'] and len(ambiguous['choices']) == 5
    assert 'Which supplier' in send(client,'their open orders',cid).json()['answer']['text']
    assert 'No matching supplier' in send(client,'supplier named Neverland Industries').json()['answer']['text']
    unknown = send(client,'Neverland Industries open orders and spend').json()['answer']
    assert 'No matching supplier' in unknown['text'] and not unknown['sections']
    csv_url = f"/api/v1/assistant/conversations/{cid}/messages/{result['message_id']}/csv"
    csv_response = client.get(csv_url)
    assert csv_response.status_code == 200
    assert csv_response.headers['content-type'].startswith('text/csv')
    exported = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert {row['section'] for row in exported} == {section['table'] for section in sections if section['rows']}
    assert len(exported) == sum(len(section['rows']) for section in sections)
    assert not send(client,'suppliers catalog orders invoices').json()['answer']['sections']
    unmatched = send(client,'unmatched invoices').json()['answer']['sections']
    assert {section['table'] for section in unmatched} == {'invoices','purchase_orders'}
    assert all(row['status'] == 'open' and not row['has_invoice'] for section in unmatched if section['table'] == 'purchase_orders' for row in section['rows'])
    with connect(path) as db:
        db.execute('UPDATE user_preferences SET preferred_fiscal_year=2025 WHERE user_id=1')
    answer = send(client,'show spend').json()['answer']
    assert 'FY2025' in answer['text'] and answer['sections'][0]['rows'] == []


def test_knowledge_role_and_conversation_isolation(workspace):
    client,path = workspace
    login(client,'analyst')
    result = send(client,'knowledge').json()
    codes = {r['code'] for r in result['answer']['sections'][0]['rows']}
    assert 'DOC-8003' in codes and 'DOC-8005' not in codes
    cid = result['conversation_id']; mid = result['message_id']
    login(client,'finance')
    assert client.get(f'/api/v1/assistant/conversations/{cid}').status_code == 404
    assert client.get(f'/api/v1/assistant/conversations/{cid}/messages/{mid}/csv').status_code == 404
    assert send(client,'orders',cid).status_code == 404
    assert client.get('/api/v1/assistant/conversations').json()['items'] == []
    codes = {r['code'] for r in send(client,'knowledge').json()['answer']['sections'][0]['rows']}
    assert 'DOC-8005' in codes and 'DOC-8003' not in codes
    with connect(path) as db:
        db.execute("UPDATE users SET role='finance_analyst' WHERE email='analyst@procurem.demo'")
    login(client,'analyst')
    reopened = client.get(f'/api/v1/assistant/conversations/{cid}').json()
    assert 'DOC-8003' not in {r['code'] for r in reopened['messages'][1]['answer']['sections'][0]['rows']}
    assert 'DOC-8003' not in client.get(f'/api/v1/assistant/conversations/{cid}/messages/{mid}/csv').text


def test_write_is_authorized_and_pending_only(workspace):
    client,path = workspace
    action = {'kind':'supplier_edit','supplier_id':1,'details':{'contact_name':'New person'}}
    login(client,'finance')
    assert 'not permitted' in send(client,'edit supplier',action=action).json()['answer']['text']
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM approvals').fetchone()[0] == 3
        original = db.execute('SELECT contact_name FROM suppliers WHERE id=1').fetchone()[0]
    login(client,'category.mgr')
    assert 'structured proposal' in send(client,'edit supplier').json()['answer']['text']
    response = send(client,'edit supplier',action=action).json()['answer']
    assert response['approval_id'] and 'pending' in response['text']
    with connect(path) as db:
        assert db.execute('SELECT contact_name FROM suppliers WHERE id=1').fetchone()[0] == original
        assert db.execute('SELECT status FROM approvals WHERE id=?',(response['approval_id'],)).fetchone()[0] == 'pending'
    assert send(client,'edit supplier',action={'kind':'supplier_edit','supplier_id':1,'details':{'risk':'invalid'}}).status_code == 422
    login(client,'analyst')
    requisition = {'kind':'requisition','details':{'supplier_id':1,'title':'Lab supplies','reason':'Needed supplies','lines':[{'description':'Tubes','quantity':2,'unit_price':'12.50'}]}}
    result = send(client,'create requisition',action=requisition).json()['answer']
    with connect(path) as db:
        approval = db.execute('SELECT * FROM approvals WHERE id=?',(result['approval_id'],)).fetchone()
        assert approval['status'] == 'pending' and approval['requester_id'] == 1
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(approval['subject_id'],)).fetchone()[0] == 'pending_approval'
        assert db.execute('SELECT count(*) FROM notifications WHERE link=?',(f"/approvals/{result['approval_id']}",)).fetchone()[0] == 1


def test_malicious_input_not_executed_and_validation(workspace):
    client,path = workspace
    login(client,'analyst')
    assert send(client,"supplier named ' OR 1=1 --").status_code == 200
    result = send(client,'DROP TABLE suppliers').json()['answer']
    assert not result['sections']
    assert send(client,' ').status_code == 422
    assert send(client,'x'*4001).status_code == 422
    assert client.get('/api/v1/assistant/conversations?page_size=101').status_code == 422
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM suppliers').fetchone()[0] >= 12


@pytest.mark.parametrize('body', [
    {}, {'message': None}, {'message': []}, {'message': 'x' * 4001},
    {'message': 'orders', 'conversation_id': '1'},
    {'message': 'orders', 'action': {'kind': 'requisition', 'details': {}}},
])
def test_invalid_assistant_requests_do_not_persist_anything(workspace, body):
    client, path = workspace
    login(client, 'analyst')
    tables = ('conversations', 'messages', 'requisitions', 'requisition_lines', 'approvals', 'notifications', 'audit_log')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    response = client.post('/api/v1/assistant/messages', json=body)
    assert response.status_code == 422
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before
