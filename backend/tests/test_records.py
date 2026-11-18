"""Exercise record endpoints with authenticated users and real SQLite data."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.database import connect
from app.main import create_app

@pytest.fixture
def workspace():
    """Start a seeded file-backed workspace."""
    with TemporaryDirectory(prefix='procurem-records-', dir=Path.home()) as folder:
        path = str(Path(folder) / 'records.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path

def login(client, email='analyst@procurem.demo'):
    """Authenticate one of the seeded users."""
    password = 'Admin@5678' if email == 'admin@procurem.demo' else 'Demo@1234'
    assert client.post('/api/v1/auth/login', json={'email':email,'password':password}).status_code == 200

def test_auth_required_and_missing_resources(workspace):
    client, _ = workspace
    for path in ['/api/v1/dashboard','/api/v1/records/suppliers','/api/v1/records/suppliers/1']:
        assert client.get(path).status_code == 401
    login(client)
    assert client.get('/api/v1/records/users').status_code == 404
    assert client.get('/api/v1/records/suppliers/9999').status_code == 404

def test_dashboard_aggregates_only_usd(workspace):
    client, path = workspace
    login(client)
    with connect(path) as db:
        db.execute("UPDATE purchase_orders SET currency='EUR' WHERE id=1")
        expected = sum((Decimal(r[0]) for r in db.execute("SELECT amount FROM purchase_orders WHERE status='open' AND currency='USD'")), Decimal('0'))
    response = client.get('/api/v1/dashboard')
    data = response.json()
    assert response.status_code == 200 and data['supplier_count'] == 12
    assert data['open_order_count'] == 8 and data['no_invoice_count'] == 8
    assert Decimal(data['open_order_usd']) == expected and data['pending_approval_count'] == 2
    assert len(data['spend']) == 6 and data['latest_month'] == '2026-06' and data['demo_data_loaded']

def test_lists_filters_search_sort_and_pagination(workspace):
    client, _ = workspace
    login(client)
    base = '/api/v1/records/suppliers'
    response = client.get(base, params={'search':'Thermo','risk':'low'})
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == 1 and data['items'][0]['name'] == 'Thermo Fisher'
    assert data['source_label'] == 'Mock · JAGGAER' and data['freshness'] == 'Real-time'
    response = client.get(base, params={'search':'%'})
    assert response.status_code == 200
    assert response.json()['total'] == 0
    response = client.get(base, params={'sort':'name','order':'asc','page_size':2})
    assert response.status_code == 200
    first = response.json()
    response = client.get(base, params={'sort':'name','order':'asc','page_size':2,'page':2})
    assert response.status_code == 200
    second = response.json()
    response = client.get(base, params={'sort':'name','order':'desc','page_size':2})
    assert response.status_code == 200
    desc = response.json()
    assert first['total'] == 12 and len(first['items']) == 2 and first['items'][0]['name'] < first['items'][1]['name']
    assert first['items'][0]['id'] != second['items'][0]['id'] and desc['items'][0]['name'] > first['items'][0]['name']
    for params in [{'page':0},{'page_size':101},{'order':'invalid'},{'sort':'name; DROP TABLE suppliers'}]:
        assert client.get(base, params=params).status_code == 422

def test_record_page_rejects_offset_that_overflows_sqlite(workspace):
    client, _ = workspace
    login(client)
    response = client.get('/api/v1/records/suppliers', params={'page': 9223372036854775808, 'page_size': 100})
    assert response.status_code == 422
    assert client.get('/api/v1/records/suppliers', params={'page': 2147483648, 'page_size': 100}).status_code == 422

    boundary = client.get('/api/v1/records/suppliers', params={'page': 2147483647, 'page_size': 100})
    assert boundary.status_code == 200
    assert boundary.json()['items'] == []
    assert boundary.json()['total'] == 12


@pytest.mark.parametrize('resource', ['suppliers','catalog','purchase-orders','invoices','contracts','requisitions','sourcing','spend','knowledge'])
def test_all_directories_and_details(workspace, resource):
    client, _ = workspace
    login(client)
    response = client.get(f'/api/v1/records/{resource}')
    assert response.status_code == 200 and response.json()['total'] > 0
    item = response.json()['items'][0]
    detail = client.get(f'/api/v1/records/{resource}/{item["id"]}')
    assert detail.status_code == 200 and detail.json()['item']['id'] == item['id']
    assert detail.json()['freshness'] == ('Analytical' if resource == 'spend' else 'Real-time')

def test_order_relationships_and_filters(workspace):
    client, _ = workspace
    login(client)
    response = client.get('/api/v1/records/purchase-orders',params={'status':'open','no_invoice':'true','supplier':'1'})
    assert response.status_code == 200
    orders = response.json()
    assert orders['total'] == 1 and orders['items'][0]['has_invoice'] == 0
    response = client.get('/api/v1/records/purchase-orders/1')
    assert response.status_code == 200
    detail = response.json()
    assert len(detail['relations']['lines']) == 2 and detail['relations']['invoices'] == []
    response = client.get('/api/v1/records/suppliers/1')
    assert response.status_code == 200
    assert len(response.json()['relations']['catalog']) > 0
    response = client.get('/api/v1/records/sourcing/1')
    assert response.status_code == 200
    assert len(response.json()['relations']['bids']) == 2
    response = client.get('/api/v1/records/invoices',params={'status':'unmatched'})
    assert response.status_code == 200
    assert response.json()['total'] == 4
    assert client.get('/api/v1/records/invoices',params={'sort':'amount'}).status_code == 200

def test_spend_year_month_and_preference(workspace):
    client, path = workspace
    login(client)
    response = client.get('/api/v1/records/spend',params={'category':'IT','from_month':2,'to_month':3})
    assert response.status_code == 200
    rows = response.json()
    assert rows['total'] == 2 and {r['month'] for r in rows['items']} == {2,3}
    assert [r['month'] for r in rows['chart']] == ['2026-02','2026-03']
    assert client.get('/api/v1/records/spend',params={'from_month':13}).status_code == 422
    with connect(path) as db:
        db.execute('UPDATE user_preferences SET preferred_fiscal_year=2025 WHERE user_id=1')
    response = client.get('/api/v1/records/spend')
    assert response.status_code == 200
    assert response.json()['total'] == 0
    response = client.get('/api/v1/records/spend',params={'year':2026})
    assert response.status_code == 200
    assert response.json()['total'] == 36

def test_knowledge_access_search_and_404(workspace):
    client, _ = workspace
    login(client)
    response = client.get('/api/v1/records/knowledge')
    assert response.status_code == 200
    docs = response.json()['items']
    assert {d['code'] for d in docs} == {'DOC-8001','DOC-8002','DOC-8003'}
    response = client.get('/api/v1/records/knowledge/3')
    assert response.status_code == 200
    assert response.json()['item']['body']
    assert client.get('/api/v1/records/knowledge/5').status_code == 404
    assert client.get('/api/v1/records/knowledge/999').status_code == 404
    response = client.get('/api/v1/records/knowledge',params={'search':'documented'})
    assert response.status_code == 200
    assert response.json()['total'] == 3
    login(client,'finance@procurem.demo')
    assert client.get('/api/v1/records/knowledge/5').status_code == 200
    assert client.get('/api/v1/records/knowledge/3').status_code == 404


@pytest.mark.parametrize('field,payload', [
    ('contact_name', '<script>alert(1)</script>'),
    ('contact_name', '<img src=x onerror=alert(1)>'),
    ('contact_email', 'x<script>alert(1)</script>@example.com'),
    ('contact_email', 'x<img/src=x/onerror=alert(1)>@example.com'),
])
def test_supplier_contact_markup_is_rejected_without_changes(workspace, field, payload):
    client, path = workspace
    login(client, 'category.mgr@procurem.demo')
    tables = ('suppliers', 'approvals', 'signatures', 'audit_log', 'notifications')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    proposed = client.post('/api/v1/suppliers/1/proposals', json={field: payload})
    assert proposed.status_code == 422
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before


def test_supplier_and_sourcing_preserve_legitimate_text(workspace):
    client, path = workspace
    login(client, 'category.mgr@procurem.demo')
    name = "O'Brien & Sons < 5"
    proposed = client.post('/api/v1/suppliers/1/proposals', json={'contact_name': name})
    assert proposed.status_code == 201
    aid = proposed.json()['approval_id']
    title = 'R&D < 5 units'
    response = client.post('/api/v1/sourcing', json={'title': title, 'event_type': 'RFQ', 'estimated_value_usd': '1.00', 'end_date': '2028-01-01'})
    assert response.status_code == 201
    event_id = response.json()['id']
    login(client, 'proc.manager@procurem.demo')
    assert client.post(f'/api/v1/approvals/{aid}/sign', json={'meaning': 'Approved', 'reason': 'Reviewed carefully', 'password': 'Demo@1234'}).status_code == 200
    with connect(path) as db:
        assert db.execute('SELECT contact_name FROM suppliers WHERE id=1').fetchone()[0] == name
        assert db.execute('SELECT title FROM sourcing_events WHERE id=?', (event_id,)).fetchone()[0] == title


@pytest.mark.parametrize('payload', ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>'])
def test_sourcing_title_markup_is_rejected_without_changes(workspace, payload):
    client, path = workspace
    login(client, 'category.mgr@procurem.demo')
    tables = ('sourcing_events', 'approvals', 'audit_log', 'notifications')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    response = client.post('/api/v1/sourcing', json={'title': payload, 'event_type': 'RFQ', 'estimated_value_usd': '1.00', 'end_date': '2028-01-01'})
    assert response.status_code == 422
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before
