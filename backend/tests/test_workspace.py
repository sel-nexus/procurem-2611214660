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
    result = client.get('/api/v1/notifications?page_size=1').json()
    assert result['total'] >= 2 and len(result['items']) == 1
    assert client.get('/api/v1/notifications?page_size=101').status_code == 422
    item = result['items'][0]
    initial = client.get('/api/v1/notifications/unread-count').json()['count']
    assert initial >= 2 and item['is_read'] == 0
    assert client.post(f"/api/v1/notifications/{item['id']}/read").json()['is_read'] == 1
    assert client.get('/api/v1/notifications/unread-count').json()['count'] == initial - 1
    assert client.post(f"/api/v1/notifications/{item['id']}/read").status_code == 200
    login(client,'analyst')
    assert client.get('/api/v1/notifications').json()['total'] == 0
    assert client.post(f"/api/v1/notifications/{item['id']}/read").status_code == 404
    assert client.post('/api/v1/notifications/99999/read').status_code == 404


def test_preferences_supplier_and_spend_persist(workspace):
    client, path = workspace
    login(client,'analyst')
    settings = client.get('/api/v1/settings').json()
    assert settings['preferred_fiscal_year'] == 2026
    supplier = settings['frequent_suppliers'][0]
    assert supplier['name'] == 'Thermo Fisher'
    assert len(settings['matrix']['roles']) == 7
    assert client.put('/api/v1/settings/fiscal-year',json={'preferred_fiscal_year':2025}).status_code == 204
    assert client.put('/api/v1/settings/fiscal-year',json={'preferred_fiscal_year':1899}).status_code == 422
    assert client.get('/api/v1/settings').json()['preferred_fiscal_year'] == 2025
    assert client.get('/api/v1/records/spend').json()['items'] == []
    assert 'FY2025' in client.post('/api/v1/assistant/messages',json={'message':'show spend'}).json()['answer']['text']
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
    first = client.post('/api/v1/assistant/messages',json={'message':'show spend'}).json()['conversation_id']
    login(client,'finance')
    other = client.post('/api/v1/assistant/messages',json={'message':'show invoices'}).json()['conversation_id']
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
    result = client.get('/api/v1/audit?'+query).json()
    assert result['total'] == 1 and result['items'][0]['record_id'] == '42'
    exported = list(csv.DictReader(io.StringIO(client.get('/api/v1/audit/csv?'+query).text)))
    assert len(exported) == 1 and exported[0]['detail'] == "' =1+1"
    assert client.get('/api/v1/audit?from_date=2026-02-01&to_date=2026-01-01').status_code == 422
    assert client.get('/api/v1/audit?sort=not_a_column').status_code == 422
    directory = client.get('/api/v1/roles?page_size=2').json()
    assert directory['total'] == 7 and len(directory['items']) == 2
    assert all('password_hash' not in row for row in directory['items'])
    assert 'seed' in client.get('/api/v1/audit/csv').text
