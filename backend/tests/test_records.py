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
    data = client.get(base, params={'search':'Thermo','risk':'low'}).json()
    assert data['total'] == 1 and data['items'][0]['name'] == 'Thermo Fisher'
    assert data['source_label'] == 'Mock · JAGGAER' and data['freshness'] == 'Real-time'
    assert client.get(base, params={'search':'%'}).json()['total'] == 0
    first = client.get(base, params={'sort':'name','order':'asc','page_size':2}).json()
    second = client.get(base, params={'sort':'name','order':'asc','page_size':2,'page':2}).json()
    desc = client.get(base, params={'sort':'name','order':'desc','page_size':2}).json()
    assert first['total'] == 12 and len(first['items']) == 2 and first['items'][0]['name'] < first['items'][1]['name']
    assert first['items'][0]['id'] != second['items'][0]['id'] and desc['items'][0]['name'] > first['items'][0]['name']
    for params in [{'page':0},{'page_size':101},{'order':'invalid'},{'sort':'name; DROP TABLE suppliers'}]:
        assert client.get(base, params=params).status_code == 422

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
    orders = client.get('/api/v1/records/purchase-orders',params={'status':'open','no_invoice':'true','supplier':'1'}).json()
    assert orders['total'] == 1 and orders['items'][0]['has_invoice'] == 0
    detail = client.get('/api/v1/records/purchase-orders/1').json()
    assert len(detail['relations']['lines']) == 2 and detail['relations']['invoices'] == []
    assert len(client.get('/api/v1/records/suppliers/1').json()['relations']['catalog']) > 0
    assert len(client.get('/api/v1/records/sourcing/1').json()['relations']['bids']) == 2
    assert client.get('/api/v1/records/invoices',params={'status':'unmatched'}).json()['total'] == 4
    assert client.get('/api/v1/records/invoices',params={'sort':'amount'}).status_code == 200

def test_spend_year_month_and_preference(workspace):
    client, path = workspace
    login(client)
    rows = client.get('/api/v1/records/spend',params={'category':'IT','from_month':2,'to_month':3}).json()
    assert rows['total'] == 2 and {r['month'] for r in rows['items']} == {2,3}
    assert [r['month'] for r in rows['chart']] == ['2026-02','2026-03']
    assert client.get('/api/v1/records/spend',params={'from_month':13}).status_code == 422
    with connect(path) as db:
        db.execute('UPDATE user_preferences SET preferred_fiscal_year=2025 WHERE user_id=1')
    assert client.get('/api/v1/records/spend').json()['total'] == 0
    assert client.get('/api/v1/records/spend',params={'year':2026}).json()['total'] == 36

def test_knowledge_access_search_and_404(workspace):
    client, _ = workspace
    login(client)
    docs = client.get('/api/v1/records/knowledge').json()['items']
    assert {d['code'] for d in docs} == {'DOC-8001','DOC-8002','DOC-8003'}
    assert client.get('/api/v1/records/knowledge/3').json()['item']['body']
    assert client.get('/api/v1/records/knowledge/5').status_code == 404
    assert client.get('/api/v1/records/knowledge/999').status_code == 404
    assert client.get('/api/v1/records/knowledge',params={'search':'documented'}).json()['total'] == 3
    login(client,'finance@procurem.demo')
    assert client.get('/api/v1/records/knowledge/5').status_code == 200
    assert client.get('/api/v1/records/knowledge/3').status_code == 404
