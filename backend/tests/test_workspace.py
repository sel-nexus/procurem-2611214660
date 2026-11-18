"""Exercise workspace permissions and persistence on file-backed SQLite."""
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
    """Start a fresh seeded API with a persistent file."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'workspace.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path


def login(client, name, password='Demo@1234'):
    """Authenticate as a seeded user."""
    result = client.post('/api/v1/auth/login', json={'email':f'{name}@procurem.demo','password':password})
    assert result.status_code == 200
    return result.json()


def test_unauthenticated_and_role_boundaries(workspace):
    client, _ = workspace
    for url in ['/api/v1/settings','/api/v1/notifications','/api/v1/notifications/unread-count','/api/v1/audit','/api/v1/audit/csv','/api/v1/roles']:
        assert client.get(url).status_code == 401
    assert client.post('/api/v1/notifications/1/read').status_code == 401
    assert client.delete('/api/v1/settings/conversations').status_code == 401
    login(client,'finance')
    assert client.get('/api/v1/audit').status_code == 403
    assert client.get('/api/v1/audit/csv').status_code == 403
    assert client.get('/api/v1/roles').status_code == 403
    login(client,'proc.manager')
    assert client.get('/api/v1/audit').status_code == 200
    assert client.get('/api/v1/roles').status_code == 403
    login(client,'compliance')
    assert client.get('/api/v1/audit/csv').status_code == 200
    assert client.get('/api/v1/roles').status_code == 200
    login(client,'admin','Admin@5678')
    assert client.get('/api/v1/audit').status_code == 200
    assert client.get('/api/v1/roles').status_code == 200


def test_notifications_private_paginated_and_marked(workspace):
    client, _ = workspace
    login(client,'proc.manager')
    response = client.get('/api/v1/notifications?page_size=1')
    assert response.status_code == 200
    result = response.json()
    assert result['total'] >= 2 and len(result['items']) == 1
    assert client.get('/api/v1/notifications?page_size=101').status_code == 422
    item = result['items'][0]
    response = client.get('/api/v1/notifications/unread-count')
    assert response.status_code == 200
    initial = response.json()['count']
    assert initial >= 2 and item['is_read'] == 0
    response = client.post(f"/api/v1/notifications/{item['id']}/read")
    assert response.status_code == 200
    assert response.json()['is_read'] == 1
    response = client.get('/api/v1/notifications/unread-count')
    assert response.status_code == 200
    assert response.json()['count'] == initial - 1
    assert client.post(f"/api/v1/notifications/{item['id']}/read").status_code == 200
    login(client,'analyst')
    response = client.get('/api/v1/notifications')
    assert response.status_code == 200
    assert response.json()['total'] == 0
    assert client.post(f"/api/v1/notifications/{item['id']}/read").status_code == 404
    assert client.post('/api/v1/notifications/99999/read').status_code == 404


def test_preferences_supplier_and_spend_persist(workspace):
    client, path = workspace
    login(client,'analyst')
    response = client.get('/api/v1/settings')
    assert response.status_code == 200
    settings = response.json()
    assert settings['preferred_fiscal_year'] == 2026
    supplier = settings['frequent_suppliers'][0]
    assert supplier['name'] == 'Thermo Fisher'
    assert len(settings['matrix']['roles']) == 7
    assert client.put('/api/v1/settings/fiscal-year',json={'preferred_fiscal_year':2025}).status_code == 204
    assert client.put('/api/v1/settings/fiscal-year',json={'preferred_fiscal_year':1899}).status_code == 422
    updated = client.get('/api/v1/settings')
    assert updated.status_code == 200 and updated.json()['preferred_fiscal_year'] == 2025
    spend = client.get('/api/v1/records/spend')
    assert spend.status_code == 200 and spend.json()['items'] == []
    answer = client.post('/api/v1/assistant/messages',json={'message':'show spend'})
    assert answer.status_code == 200 and 'FY2025' in answer.json()['answer']['text']
    login(client,'finance')
    assert client.delete(f"/api/v1/settings/frequent-suppliers/{supplier['id']}").status_code == 404
    login(client,'analyst')
    assert client.delete(f"/api/v1/settings/frequent-suppliers/{supplier['id']}").status_code == 204
    assert client.delete(f"/api/v1/settings/frequent-suppliers/{supplier['id']}").status_code == 404
    with connect(path) as db:
        assert db.execute('SELECT preferred_fiscal_year FROM user_preferences WHERE user_id=1').fetchone()[0] == 2025
        assert db.execute('SELECT name FROM suppliers WHERE id=?',(supplier['id'],)).fetchone()[0] == 'Thermo Fisher'


def test_clear_only_own_history_preserves_audit(workspace):
    client,path = workspace
    login(client,'analyst')
    response = client.post('/api/v1/assistant/messages',json={'message':'show spend'})
    assert response.status_code == 200
    first = response.json()['conversation_id']
    login(client,'finance')
    response = client.post('/api/v1/assistant/messages',json={'message':'show invoices'})
    assert response.status_code == 200
    other = response.json()['conversation_id']
    login(client,'analyst')
    assert client.delete('/api/v1/settings/conversations').status_code == 204
    assert client.get(f'/api/v1/assistant/conversations/{first}').status_code == 404
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM messages WHERE conversation_id=?',(first,)).fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM messages WHERE conversation_id=?',(other,)).fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM audit_log WHERE action='query'").fetchone()[0] == 2


def test_audit_filter_export_and_formula_safety(workspace):
    client,path = workspace
    with connect(path) as db:
        db.execute("INSERT INTO audit_log(user_id,role,action,record_type,record_id,detail,created_at) VALUES (1,'analyst','query','test','42',' =1+1','2026-01-02T10:00:00+00:00')")
        db.execute("INSERT INTO audit_log(user_id,role,action,record_type,record_id,detail,created_at) VALUES (2,'category_manager','query','test','43','other','2026-01-03T10:00:00+00:00')")
    login(client,'compliance')
    query = 'user_id=1&action=query&from_date=2026-01-02&to_date=2026-01-02'
    response = client.get('/api/v1/audit?'+query)
    assert response.status_code == 200
    result = response.json()
    assert result['total'] == 1 and result['items'][0]['record_id'] == '42'
    response = client.get('/api/v1/audit/csv?'+query)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/csv')
    exported = list(csv.DictReader(io.StringIO(response.text)))
    assert len(exported) == 1 and exported[0]['detail'] == "' =1+1"
    assert client.get('/api/v1/audit?from_date=2026-02-01&to_date=2026-01-01').status_code == 422
    assert client.get('/api/v1/audit?sort=not_a_column').status_code == 422
    response = client.get('/api/v1/roles?page_size=2')
    assert response.status_code == 200
    directory = response.json()
    assert directory['total'] == 7 and len(directory['items']) == 2
    assert all('password_hash' not in row for row in directory['items'])
    response = client.get('/api/v1/audit/csv')
    assert response.status_code == 200
    assert 'seed' in response.text


def test_pending_counts_are_role_scoped_and_actionable(workspace):
    client, path = workspace
    endpoint = '/api/v1/approvals/pending-count'
    assert client.get(endpoint).status_code == 401
    for name, password in [('analyst', 'Demo@1234'), ('finance', 'Demo@1234'), ('admin', 'Admin@5678')]:
        login(client, name, password)
        assert client.get(endpoint).status_code == 403
    login(client, 'proc.manager')
    response = client.get(endpoint)
    assert response.status_code == 200 and response.json() == {'count': 2}
    assert response.headers['cache-control'] == 'no-store'
    login(client, 'compliance')
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {'count': 0}
    login(client, 'proc.manager')
    response = client.post('/api/v1/approvals/2/sign', json={'meaning': 'Approved', 'reason': 'Reviewed carefully', 'password': 'Demo@1234'})
    assert response.status_code == 200 and response.json()['status'] == 'pending_second'
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {'count': 1}
    login(client, 'compliance')
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {'count': 1}
    with connect(path) as db:
        db.execute('UPDATE approvals SET requester_id=6 WHERE id=2')
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {'count': 0}
    with connect(path) as db:
        db.execute('UPDATE approvals SET requester_id=1 WHERE id=2')
        db.execute("INSERT INTO signatures (approval_id,signer_id,meaning,reason,signed_at) VALUES (2,6,'Approved','Already signed','2026-01-01')")
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {'count': 0}
    login(client, 'proc.manager')
    with connect(path) as db:
        db.execute('UPDATE approvals SET requester_id=3 WHERE id=1')
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {'count': 0}


def test_fiscal_year_boundaries_and_clear(workspace):
    client, _ = workspace
    login(client, 'analyst')
    endpoint = '/api/v1/settings/fiscal-year'
    for year in (0, 1899, 10000):
        assert client.put(endpoint, json={'preferred_fiscal_year': year}).status_code == 422
    for year in (1900, 9999, None):
        assert client.put(endpoint, json={'preferred_fiscal_year': year}).status_code == 204
        response = client.get('/api/v1/settings')
        assert response.status_code == 200
        assert response.json()['preferred_fiscal_year'] == year


@pytest.mark.parametrize('body', [
    {},
    {'preferred_fiscal_year': 'not-a-year'},
    {'preferred_fiscal_year': []},
    {'preferred_fiscal_year': 2025.5},
    {'preferred_fiscal_year': 10000},
    {'preferred_fiscal_year': 10**100},
])
def test_invalid_fiscal_year_preserves_preferences(workspace, body):
    client, path = workspace
    login(client, 'analyst')
    with connect(path) as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM user_preferences ORDER BY user_id')]
    response = client.put('/api/v1/settings/fiscal-year', json=body)
    assert response.status_code == 422
    with connect(path) as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM user_preferences ORDER BY user_id')] == before
    response = client.get('/api/v1/settings')
    assert response.status_code == 200
    assert response.json()['preferred_fiscal_year'] == 2026
