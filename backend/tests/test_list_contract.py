"""Exercise list pagination, ordering, validation and access on SQLite."""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import connect
from app.main import create_app


CONVERSATIONS = '/api/v1/assistant/conversations'
NOTIFICATIONS = '/api/v1/notifications'
ROLES = '/api/v1/roles'


@pytest.fixture(scope='module')
def listing():
    """Start a seeded API with predictable owned and foreign rows."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'lists.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            response = client.post('/api/v1/auth/login', json={'email': 'compliance@procurem.demo', 'password': 'Demo@1234'})
            assert response.status_code == 200
            user_id = response.json()['id']
            with connect(path) as db:
                other_id = db.execute("SELECT id FROM users WHERE email='finance@procurem.demo'").fetchone()[0]
                db.execute('DELETE FROM notifications WHERE user_id IN (?,?)', (user_id, other_id))
                db.executemany('INSERT INTO conversations(user_id,title,created_at) VALUES (?,?,?)', [
                    (user_id, 'Zulu', '2026-01-01'), (user_id, 'Alpha', '2026-01-02'),
                    (user_id, 'Alpha', '2026-01-02'), (other_id, 'Private', '2026-01-03'),
                ])
                db.executemany('INSERT INTO notifications(user_id,title,body,created_at,is_read) VALUES (?,?,?,?,?)', [
                    (user_id, 'Zulu', 'z', '2026-01-01', 1), (user_id, 'Alpha', 'a', '2026-01-02', 0),
                    (user_id, 'Alpha', 'b', '2026-01-02', 0), (other_id, 'Private', 'p', '2026-01-03', 0),
                ])
            yield client, path


@pytest.mark.parametrize('url,default_sort,default_order', [
    (CONVERSATIONS, 'id', 'desc'),
    (NOTIFICATIONS, 'created_at', 'desc'),
    (ROLES, 'display_name', 'asc'),
])
def test_defaults_and_pagination(listing, url, default_sort, default_order):
    client, path = listing
    default = client.get(url)
    assert default.status_code == 200
    body = default.json()
    assert body['page'] == 1 and body['page_size'] == 20
    assert body['total'] == (7 if url == ROLES else 3)
    assert body == client.get(url, params={'sort': default_sort, 'order': default_order}).json()
    with connect(path) as db:
        user_id = db.execute("SELECT id FROM users WHERE email='compliance@procurem.demo'").fetchone()[0]
        if url == CONVERSATIONS:
            expected_ids = [row[0] for row in db.execute('SELECT id FROM conversations WHERE user_id=? ORDER BY id DESC', (user_id,))]
        elif url == NOTIFICATIONS:
            expected_ids = [row[0] for row in db.execute('SELECT id FROM notifications WHERE user_id=? ORDER BY created_at DESC,id DESC', (user_id,))]
        else:
            expected_ids = [row[0] for row in db.execute('SELECT id FROM users ORDER BY display_name COLLATE NOCASE,id')]
    assert [row['id'] for row in body['items']] == expected_ids
    assert len(body['items']) == body['total']
    page = client.get(url, params={'page': 2, 'page_size': 1})
    assert page.status_code == 200
    assert page.json()['items'] == body['items'][1:2]
    assert page.json()['page'] == 2 and page.json()['page_size'] == 1
    assert page.json()['total'] == body['total']
    assert client.get(url, params={'page': 100, 'page_size': 100}).json()['items'] == []
    if url == ROLES:
        assert 'matrix' in body
        assert all('password_hash' not in row for row in body['items'])
    else:
        assert all(row['title'] != 'Private' for row in body['items'])


@pytest.mark.parametrize('url,field', [
    (CONVERSATIONS, 'id'), (CONVERSATIONS, 'title'), (CONVERSATIONS, 'created_at'),
    (NOTIFICATIONS, 'id'), (NOTIFICATIONS, 'title'), (NOTIFICATIONS, 'created_at'), (NOTIFICATIONS, 'is_read'),
    (ROLES, 'id'), (ROLES, 'display_name'), (ROLES, 'email'), (ROLES, 'role'), (ROLES, 'status'),
])
@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_whitelisted_sort_and_order(listing, url, field, order):
    client, _ = listing
    response = client.get(url, params={'sort': field, 'order': order})
    assert response.status_code == 200
    items = response.json()['items']
    # Sorting is stable on id: roles use ascending, the other lists descending.
    by_id = sorted(items, key=lambda row: row['id'], reverse=url != ROLES)
    def key(row):
        value = row[field]
        return value.lower() if isinstance(value, str) and field in ('title', 'display_name', 'email', 'role', 'status') else value
    expected = sorted(by_id, key=key, reverse=order == 'desc')
    assert [row['id'] for row in items] == [row['id'] for row in expected]
    page = client.get(url, params={'sort': field, 'order': order, 'page': 2, 'page_size': 1})
    assert page.status_code == 200
    assert page.json()['items'] == items[1:2]


@pytest.mark.parametrize('url', [CONVERSATIONS, NOTIFICATIONS, ROLES])
@pytest.mark.parametrize('params', [
    {'page': 0}, {'page': -1}, {'page': 'bad'}, {'page': '9223372036854775808'}, {'page_size': 0},
    {'page_size': 101}, {'page_size': 'bad'}, {'sort': ''}, {'sort': 'password_hash'},
    {'sort': 'id; DROP TABLE users;--'}, {'order': ''}, {'order': 'ASC'},
    {'order': 'desc; DROP TABLE users;--'},
])
def test_invalid_parameters_rejected_without_sql_injection(listing, url, params):
    client, path = listing
    assert client.get(url, params=params).status_code == 422
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 7


@pytest.mark.parametrize('url', [CONVERSATIONS, NOTIFICATIONS, ROLES])
def test_authentication_and_authorization(listing, url):
    client, _ = listing
    with TestClient(client.app) as anonymous:
        assert anonymous.get(url, params={'sort': 'id', 'order': 'asc'}).status_code == 401
        assert anonymous.post('/api/v1/auth/login', json={'email': 'finance@procurem.demo', 'password': 'Demo@1234'}).status_code == 200
        response = anonymous.get(url, params={'sort': 'id', 'order': 'asc'})
        if url == ROLES:
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert [item['title'] for item in response.json()['items']] == ['Private']


@pytest.fixture(scope='module')
def admin_lists():
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'admin-lists.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            login = client.post('/api/v1/auth/login', json={'email': 'admin@procurem.demo', 'password': 'Admin@5678'})
            assert login.status_code == 200
            yield client, path


@pytest.mark.parametrize('url,field,sql', [
    ('/api/v1/records/suppliers', 'code', 'code COLLATE NOCASE'),
    ('/api/v1/records/suppliers', 'name', 'name COLLATE NOCASE'),
    ('/api/v1/records/suppliers', 'category', 'category COLLATE NOCASE'),
    ('/api/v1/records/suppliers', 'country', 'country COLLATE NOCASE'),
    ('/api/v1/records/suppliers', 'status', 'status COLLATE NOCASE'),
    ('/api/v1/records/suppliers', 'risk', 'risk COLLATE NOCASE'),
    ('/api/v1/records/suppliers', 'spend_ytd_usd', 'CAST(spend_ytd_usd AS NUMERIC)'),
    ('/api/v1/approvals', 'id', 'a.id'),
    ('/api/v1/approvals', 'title', 'a.title'),
    ('/api/v1/approvals', 'approval_type', 'a.approval_type'),
    ('/api/v1/approvals', 'requester_name', 'u.display_name'),
    ('/api/v1/approvals', 'amount_usd', 'CAST(a.amount_usd AS NUMERIC)'),
    ('/api/v1/approvals', 'risk', 'a.risk'),
    ('/api/v1/approvals', 'status', 'a.status'),
    ('/api/v1/approvals', 'created_at', 'a.created_at'),
    ('/api/v1/approvals', 'signatures_collected', '(SELECT count(*) FROM signatures s WHERE s.approval_id=a.id)'),
    ('/api/v1/approvals', 'signatures_required', "CASE WHEN a.risk='high' THEN 2 ELSE 1 END"),
    ('/api/v1/users', 'display_name', 'display_name COLLATE NOCASE'),
    ('/api/v1/users', 'email', 'email COLLATE NOCASE'),
    ('/api/v1/users', 'role', 'role COLLATE NOCASE'),
    ('/api/v1/users', 'status', 'status COLLATE NOCASE'),
])
@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_record_approval_and_user_sort_directions_and_pages(admin_lists, url, field, sql, order):
    client, path = admin_lists
    response = client.get(url, params={'sort': field, 'order': order, 'page_size': 100})
    assert response.status_code == 200
    body = response.json()
    with connect(path) as db:
        if url.endswith('/suppliers'):
            query = f'SELECT id FROM suppliers ORDER BY {sql} {order.upper()}, id ASC'
        elif url.endswith('/approvals'):
            query = f'SELECT a.id FROM approvals a JOIN users u ON u.id=a.requester_id ORDER BY {sql} {order.upper()}, a.id ASC'
        else:
            query = f'SELECT id FROM users ORDER BY {sql} {order.upper()}, id ASC'
        expected = [row[0] for row in db.execute(query)]
    assert body['total'] == len(expected)
    assert [row['id'] for row in body['items']] == expected
    page = client.get(url, params={'sort': field, 'order': order, 'page': 2, 'page_size': 1})
    assert page.status_code == 200
    assert page.json()['items'] == body['items'][1:2]
    assert page.json()['total'] == body['total']


@pytest.mark.parametrize('url', ['/api/v1/records/suppliers', '/api/v1/approvals', '/api/v1/users'])
@pytest.mark.parametrize('params', [
    {'page': 0}, {'page': -1}, {'page': 'bad'}, {'page_size': 0}, {'page_size': 101},
    {'page_size': 'bad'}, {'sort': 'password_hash'}, {'sort': 'id; DROP TABLE users;--'},
    {'order': 'ASC'}, {'order': ''}, {'order': 'desc; DROP TABLE users;--'},
])
def test_record_approval_and_user_list_invalid_parameters(admin_lists, url, params):
    client, path = admin_lists
    response = client.get(url, params=params)
    assert response.status_code == 422
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 7


def test_record_filters_user_search_and_defaults(admin_lists):
    client, _ = admin_lists
    for url in ['/api/v1/records/suppliers', '/api/v1/approvals', '/api/v1/users']:
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()['page'] == 1 and response.json()['page_size'] == 20
        empty = client.get(url, params={'page': 100, 'page_size': 100})
        assert empty.status_code == 200 and empty.json()['items'] == []
    filtered = client.get('/api/v1/records/suppliers', params={'risk': 'high', 'status': 'active'})
    assert filtered.status_code == 200
    assert filtered.json()['items'] and all(row['risk'] == 'high' and row['status'] == 'active' for row in filtered.json()['items'])
    users = client.get('/api/v1/users', params={'search': 'priya'})
    assert users.status_code == 200 and [row['display_name'] for row in users.json()['items']] == ['Priya Shah']
    assert client.get('/api/v1/users', params={'search': 'x' * 101}).status_code == 422
    assert client.get('/api/v1/records/suppliers', params={'search': 'x' * 201}).status_code == 422



@pytest.mark.parametrize('resource,field', [
    *[('catalog', field) for field in ('code', 'name', 'category', 'supplier_name', 'unit_price', 'currency', 'status')],
    *[('purchase-orders', field) for field in ('code', 'supplier_name', 'category', 'amount', 'currency', 'status', 'requester_name', 'due_date', 'has_invoice')],
    *[('invoices', field) for field in ('code', 'supplier_name', 'po_code', 'amount', 'currency', 'status', 'invoice_date')],
    *[('contracts', field) for field in ('code', 'supplier_name', 'contract_type', 'value_usd', 'start_date', 'end_date', 'status')],
    *[('requisitions', field) for field in ('code', 'title', 'supplier_name', 'total_amount_usd', 'status', 'requester_name', 'created_at')],
    *[('sourcing', field) for field in ('code', 'title', 'event_type', 'status', 'end_date', 'bid_count', 'estimated_value_usd')],
    *[('spend', field) for field in ('category', 'year', 'month', 'amount_usd', 'supplier_name')],
    *[('knowledge', field) for field in ('code', 'title', 'version', 'updated_at')],
])
@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_other_record_sorts_are_stable_across_pages(admin_lists, resource, field, order):
    from decimal import Decimal

    client, _ = admin_lists
    url = f'/api/v1/records/{resource}'
    params = {'sort': field, 'order': order, 'page_size': 100}
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    items = response.json()['items']
    assert len(items) > 1
    money = {'unit_price', 'amount', 'value_usd', 'total_amount_usd', 'estimated_value_usd', 'amount_usd'}
    def key(row):
        value = row[field]
        if value is None:
            return (0, '')
        return (1, Decimal(value) if field in money else value.lower() if isinstance(value, str) else value)
    expected = sorted(sorted(items, key=lambda row: row['id']), key=key, reverse=order == 'desc')
    assert [row['id'] for row in items] == [row['id'] for row in expected]
    page = client.get(url, params={**params, 'page': 2, 'page_size': 2})
    assert page.status_code == 200 and page.json()['items'] == items[2:4]
    assert page.json()['total'] == len(items)
    assert client.get(url, params={'sort': 'id; DROP TABLE users;--'}).status_code == 422


@pytest.mark.parametrize('resource,params,expected_ids', [
    ('catalog', {'category': 'Lab Reagents', 'supplier': '1'}, [1, 13]),
    ('purchase-orders', {'supplier': '1', 'status': 'open', 'no_invoice': 'true'}, [1]),
    ('invoices', {'supplier': '1', 'status': 'unmatched'}, [1]),
    ('contracts', {'supplier': '1', 'status': 'expiring_soon'}, [1]),
    ('requisitions', {'search': 'REQ-2002'}, [2]),
    ('sourcing', {'search': 'SE-3002'}, [2]),
    ('knowledge', {'search': 'Procurement Policy'}, [1]),
])
def test_other_record_filters_match_expected_rows(admin_lists, resource, params, expected_ids):
    client, _ = admin_lists
    response = client.get(f'/api/v1/records/{resource}', params=params)
    assert response.status_code == 200
    assert [row['id'] for row in response.json()['items']] == expected_ids
    assert response.json()['total'] == len(expected_ids)


def test_spend_year_month_and_category_filters_and_chart(admin_lists):
    client, _ = admin_lists
    response = client.get('/api/v1/records/spend', params={'year': 2026, 'category': 'Lab Reagents', 'from_month': 2, 'to_month': 3, 'sort': 'month'})
    assert response.status_code == 200
    body = response.json()
    assert [(row['month'], row['amount_usd']) for row in body['items']] == [(2, '1200.00'), (3, '1300.00')]
    assert body['total'] == 2 and body['chart'] == [{'month': '2026-02', 'amount_usd': '1200.00'}, {'month': '2026-03', 'amount_usd': '1300.00'}]
    assert client.get('/api/v1/records/spend', params={'year': 2025}).json()['items'] == []
    assert client.get('/api/v1/records/spend', params={'from_month': 13}).status_code == 422



@pytest.mark.parametrize('resource,default_sort', [
    ('catalog', 'code'), ('purchase-orders', 'code'), ('invoices', 'code'),
    ('contracts', 'code'), ('requisitions', 'code'), ('sourcing', 'code'),
    ('spend', 'category'), ('knowledge', 'code'),
])
def test_other_record_defaults_and_invalid_pagination(admin_lists, resource, default_sort):
    client, _ = admin_lists
    url = f'/api/v1/records/{resource}'
    default = client.get(url)
    explicit = client.get(url, params={'page': 1, 'page_size': 20, 'sort': default_sort, 'order': 'asc'})
    assert default.status_code == explicit.status_code == 200
    assert default.json() == explicit.json()
    assert default.json()['page'] == 1 and default.json()['page_size'] == 20
    for params in ({'page': 0}, {'page_size': 0}, {'page_size': 101}, {'order': 'ASC'}):
        assert client.get(url, params=params).status_code == 422
    empty = client.get(url, params={'page': 100, 'page_size': 100})
    assert empty.status_code == 200 and empty.json()['items'] == []
