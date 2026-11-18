"""Exercise intent routing and clarification precedence through the assistant API."""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import connect
from app.main import create_app


@pytest.fixture(scope='module')
def assistant_client():
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'routing.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            response = client.post('/api/v1/auth/login', json={'email': 'analyst@procurem.demo', 'password': 'Demo@1234'})
            assert response.status_code == 200
            yield client, path


@pytest.mark.parametrize('message,resources', [
    ('vendors', ['suppliers']),
    ('items', ['catalog']),
    ('PO-1001', ['purchase-orders']),
    ('invoices', ['invoices']),
    ('contracts', ['contracts']),
    ('requisitions', ['requisitions']),
    ('rfq', ['sourcing']),
    ('categories', ['spend']),
    ('policy', ['knowledge']),
    ('unmatched', ['invoices', 'purchase-orders']),
    ('catalog and contracts', ['catalog', 'contracts']),
])
def test_recognized_intents_route_to_expected_sections(assistant_client, message, resources):
    client, _ = assistant_client
    response = client.post('/api/v1/assistant/messages', json={'message': message})
    assert response.status_code == 200
    answer = response.json()['answer']
    assert [section['resource'] for section in answer['sections']] == resources
    assert all(section['table'] and section['source'] and isinstance(section['rows'], list) for section in answer['sections'])


@pytest.mark.parametrize('message,expected', [
    ('status', 'Which area do you mean?'),
    ('show me everything', 'Which area do you mean?'),
    ('suppliers invoices contracts sourcing', 'Which area do you mean?'),
    ('their orders', 'Which supplier do you mean?'),
    ('supplier named ZzzUnknown', 'No matching supplier was found.'),
    ('ZzzUnknown orders and spend', 'No matching supplier was found.'),
    ('hello', 'I can answer questions about suppliers'),
    ('create requisition', 'Please provide a complete structured proposal'),
    ('edit supplier', 'Your role is not permitted'),
    ('award event', 'Your role is not permitted'),
    ('create sourcing event', 'Your role is not permitted'),
    ('delete anything', 'Please provide a complete structured proposal'),
])
def test_clarification_and_write_intent_precedence(assistant_client, message, expected):
    client, path = assistant_client
    with connect(path) as db:
        before = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('suppliers', 'sourcing_events', 'requisitions', 'approvals')]
    response = client.post('/api/v1/assistant/messages', json={'message': message})
    assert response.status_code == 200
    answer = response.json()['answer']
    assert answer['text'].startswith(expected)
    assert answer['sections'] == []
    with connect(path) as db:
        after = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('suppliers', 'sourcing_events', 'requisitions', 'approvals')]
    assert after == before


def test_purchase_order_filter_branches(assistant_client):
    client, _ = assistant_client
    for message, status, without_invoice in [('open orders', 'open', False), ('overdue orders', 'overdue', False), ('orders without invoice', 'open', True), ('unmatched', 'open', True)]:
        response = client.post('/api/v1/assistant/messages', json={'message': message})
        assert response.status_code == 200
        section = next(section for section in response.json()['answer']['sections'] if section['resource'] == 'purchase-orders')
        assert section['rows']
        assert all(row['status'] == status and (not without_invoice or not row['has_invoice']) for row in section['rows'])


def test_purchase_order_code_matches_exact_row_and_composes_with_filters(assistant_client):
    client, path = assistant_client
    with connect(path) as db:
        row = db.execute('SELECT p.id, s.name FROM purchase_orders p JOIN suppliers s ON s.id=p.supplier_id WHERE p.code=?', ('PO-1001',)).fetchone()
    for message in ('po-1001', f'open orders PO-1001 {row["name"]}', 'open orders without invoice PO-1001'):
        response = client.post('/api/v1/assistant/messages', json={'message': message})
        assert response.status_code == 200
        section = next(section for section in response.json()['answer']['sections'] if section['resource'] == 'purchase-orders')
        assert [(item['id'], item['code']) for item in section['rows']] == [(row['id'], 'PO-1001')]
        assert [citation['code'] for citation in section['citations']] == ['PO-1001']
    for message in ('overdue orders PO-1001', 'Merck open orders PO-1001'):
        response = client.post('/api/v1/assistant/messages', json={'message': message})
        assert response.status_code == 200
        section = next(section for section in response.json()['answer']['sections'] if section['resource'] == 'purchase-orders')
        assert section['rows'] == [] and section['citations'] == []


def test_distinct_purchase_order_codes_require_clarification_without_proposal(assistant_client):
    client, path = assistant_client
    tables = ('purchase_orders', 'requisitions', 'requisition_lines', 'approvals', 'sourcing_events', 'suppliers')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    response = client.post('/api/v1/assistant/messages', json={'message': 'PO-1001 and PO-1002'})
    assert response.status_code == 200
    answer = response.json()['answer']
    assert answer['text'] == 'Which purchase order do you mean?'
    assert answer['sections'] == []
    assert 'approval_id' not in answer
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before


def test_repeated_purchase_order_code_returns_exact_match(assistant_client):
    client, path = assistant_client
    with connect(path) as db:
        row = db.execute('SELECT id, code FROM purchase_orders WHERE code=?', ('PO-1001',)).fetchone()
    response = client.post('/api/v1/assistant/messages', json={'message': 'PO-1001 and po-1001'})
    assert response.status_code == 200
    answer = response.json()['answer']
    assert answer['text'] == 'Found 1 matching record(s).'
    assert len(answer['sections']) == 1
    section = answer['sections'][0]
    assert section['resource'] == 'purchase-orders'
    assert [(item['id'], item['code']) for item in section['rows']] == [(row['id'], row['code'])]
    assert section['citations'] == [{'id': row['id'], 'code': row['code'], 'href': f"/purchase-orders/{row['id']}"}]
    assert 'approval_id' not in answer


@pytest.mark.parametrize('code', ['PO-100', 'PO-999999'])
def test_unknown_purchase_order_code_returns_no_match(assistant_client, code):
    client, _ = assistant_client
    response = client.post('/api/v1/assistant/messages', json={'message': code})
    assert response.status_code == 200
    answer = response.json()['answer']
    assert answer['text'] == 'No matching records were found.'
    assert len(answer['sections']) == 1
    assert answer['sections'][0]['resource'] == 'purchase-orders'
    assert answer['sections'][0]['rows'] == []
    assert answer['sections'][0]['citations'] == []
