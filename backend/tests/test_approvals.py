"""Exercise approvals against isolated seeded file-backed SQLite databases."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.database import connect
from app.main import create_app

@pytest.fixture
def workspace():
    """Start an isolated workspace with the real seed."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'test.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path

def login(client, role):
    """Sign in as a seeded role."""
    email = {'analyst':'analyst','manager':'proc.manager','compliance':'compliance','sourcing':'sourcing'}[role]
    assert client.post('/api/v1/auth/login',json={'email':f'{email}@procurem.demo','password':'Demo@1234'}).status_code == 200

def signature(meaning='Approved', password='Demo@1234', reason='Reviewed carefully'):
    """Build a valid signature request."""
    return {'meaning':meaning,'password':password,'reason':reason}

def draft(client, price='123.45'):
    """Create a requisition and return its identifier."""
    response = client.post('/api/v1/requisitions',json={'supplier_id':1,'title':'Test requisition','reason':'Needed for work','lines':[{'description':'Supplies','quantity':2,'unit_price':price}]})
    assert response.status_code == 201, response.text
    return response.json()['id']

def test_low_value_draft_submit_sign_and_persistence(workspace):
    client,path = workspace
    assert client.get('/api/v1/approvals').status_code == 401
    login(client,'analyst')
    rid = draft(client,'0.10')
    with connect(path) as db:
        assert db.execute('SELECT total_amount_usd,status FROM requisitions WHERE id=?',(rid,)).fetchone()[:] == ('0.20','draft')
    response = client.post(f'/api/v1/requisitions/{rid}/submit')
    assert response.status_code == 200
    aid = response.json()['approval_id']
    assert client.post(f'/api/v1/requisitions/{rid}/submit').status_code == 409
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code == 403
    login(client,'manager')
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature(password='incorrect')).status_code == 422
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature(reason='short')).status_code == 422
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 0
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(rid,)).fetchone()[0] == 'pending_approval'
    response = client.post(f'/api/v1/approvals/{aid}/sign',json=signature())
    assert response.status_code == 200 and response.json()['status'] == 'approved'
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code == 403
    with connect(path) as db:
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(rid,)).fetchone()[0] == 'approved'
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit_log WHERE action='sign' AND record_id=?",(str(aid),)).fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM notifications WHERE user_id=1 AND link=?',(f'/approvals/{aid}',)).fetchone()[0] == 1

def test_threshold_and_rejection(workspace):
    client,path = workspace
    login(client,'analyst')
    rid = draft(client,'5000.00')
    response = client.post(f'/api/v1/requisitions/{rid}/submit')
    assert response.status_code == 200
    aid = response.json()['approval_id']
    response = client.get(f'/api/v1/approvals/{aid}')
    assert response.status_code == 200
    assert response.json()['risk'] == 'high'
    login(client,'compliance')
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code == 403
    login(client,'manager')
    response = client.post(f'/api/v1/approvals/{aid}/sign',json=signature())
    assert response.status_code == 200
    assert response.json()['status'] == 'pending_second'
    with connect(path) as db:
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(rid,)).fetchone()[0] == 'pending_approval'
        assert db.execute('SELECT count(*) FROM notifications WHERE user_id=6 AND link=?',(f'/approvals/{aid}',)).fetchone()[0] == 1
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code == 403
    login(client,'compliance')
    response = client.post(f'/api/v1/approvals/{aid}/sign',json=signature('Rejected'))
    assert response.status_code == 200
    assert response.json()['status'] == 'rejected'
    with connect(path) as db:
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(rid,)).fetchone()[0] == 'rejected'
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 2

def test_seeded_award_requires_two_and_applies_once(workspace):
    client,path = workspace
    login(client,'sourcing')
    assert client.post('/api/v1/approvals/2/sign',json=signature()).status_code == 403
    login(client,'manager')
    response = client.post('/api/v1/approvals/2/sign',json=signature())
    assert response.status_code == 200
    assert response.json()['status'] == 'pending_second'
    with connect(path) as db:
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=1').fetchone()[:] == ('active',None)
    login(client,'compliance')
    response = client.post('/api/v1/approvals/2/sign',json=signature())
    assert response.status_code == 200
    assert response.json()['status'] == 'approved'
    with connect(path) as db:
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=1').fetchone()[:] == ('awarded',1)
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=2').fetchone()[0] == 2

def test_validation_and_authorization(workspace):
    client,_ = workspace
    login(client,'manager')
    body = {'supplier_id':1,'title':'Test','reason':'Need','lines':[{'description':'a','quantity':1,'unit_price':'1'}]}
    assert client.post('/api/v1/requisitions',json=body).status_code == 403
    login(client,'analyst')
    for change in [{'supplier_id':9999},{'title':' '},{'lines':[]},{'lines':[{'description':'x','quantity':0,'unit_price':'1'}]},{'lines':[{'description':'x','quantity':1,'unit_price':'0'}]},{'lines':[{'description':'x','quantity':1,'unit_price':'1.001'}]}]:
        assert client.post('/api/v1/requisitions',json={**body,**change}).status_code == 422
    assert client.get('/api/v1/approvals/9999').status_code == 404
    assert client.get('/api/v1/approvals?page_size=101').status_code == 422

def test_requester_and_duplicate_concurrent_signatures(workspace):
    from concurrent.futures import ThreadPoolExecutor
    client,path = workspace
    login(client,'analyst')
    rid = draft(client)
    response = client.post(f'/api/v1/requisitions/{rid}/submit')
    assert response.status_code == 200
    aid = response.json()['approval_id']
    with connect(path) as db:
        db.execute("UPDATE users SET role='procurement_manager' WHERE id=1")
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code == 403
    login(client,'manager')
    def attempt():
        return client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == [200,403]
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 1
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(rid,)).fetchone()[0] == 'approved'


def test_high_requisition_approval_and_low_rejection(workspace):
    client, path = workspace
    login(client, 'analyst')
    high_id = draft(client, '5000.00')
    response = client.post(f'/api/v1/requisitions/{high_id}/submit')
    assert response.status_code == 200
    high_approval = response.json()['approval_id']
    low_id = draft(client, '4999.99')
    response = client.post(f'/api/v1/requisitions/{low_id}/submit')
    assert response.status_code == 200
    low_approval = response.json()['approval_id']
    response = client.get(f'/api/v1/approvals/{low_approval}')
    assert response.status_code == 200
    assert response.json()['risk'] == 'low'
    login(client, 'manager')
    response = client.post(f'/api/v1/approvals/{high_approval}/sign', json=signature())
    assert response.status_code == 200
    assert response.json()['status'] == 'pending_second'
    response = client.post(f'/api/v1/approvals/{low_approval}/sign', json=signature('Rejected'))
    assert response.status_code == 200
    assert response.json()['status'] == 'rejected'
    login(client, 'compliance')
    response = client.post(f'/api/v1/approvals/{high_approval}/sign', json=signature())
    assert response.status_code == 200
    assert response.json()['status'] == 'approved'
    with connect(path) as db:
        assert db.execute('SELECT status FROM requisitions WHERE id=?', (high_id,)).fetchone()[0] == 'approved'
        assert db.execute('SELECT status FROM requisitions WHERE id=?', (low_id,)).fetchone()[0] == 'rejected'
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?', (high_approval,)).fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?', (low_approval,)).fetchone()[0] == 1
        audit_details = [row[0] for row in db.execute("SELECT detail FROM audit_log WHERE action='sign'")]
        assert all('Demo@1234' not in detail for detail in audit_details)


def test_failed_application_rolls_back_signature(workspace):
    client,path = workspace
    with connect(path) as db:
        db.execute("UPDATE sourcing_events SET status='closed' WHERE id=1")
    login(client,'manager')
    assert client.post('/api/v1/approvals/2/sign',json=signature()).status_code == 200
    login(client,'compliance')
    assert client.post('/api/v1/approvals/2/sign',json=signature()).status_code == 409
    with connect(path) as db:
        assert db.execute('SELECT status FROM approvals WHERE id=2').fetchone()[0] == 'pending_second'
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=2').fetchone()[0] == 1


def test_approval_inbox_pagination_returns_all_seeded_records(workspace):
    client, path = workspace
    login(client, 'analyst')
    with connect(path) as db:
        expected = [tuple(row) for row in db.execute('SELECT id, status, risk FROM approvals ORDER BY id')]
    pages = []
    for page in (1, 2, 3, 4):
        response = client.get('/api/v1/approvals', params={'page': page, 'page_size': 1, 'sort': 'id', 'order': 'asc'})
        assert response.status_code == 200
        body = response.json()
        assert (body['total'], body['page'], body['page_size']) == (3, page, 1)
        pages.extend(body['items'])
    assert [(item['id'], item['status'], item['risk']) for item in pages] == expected
    assert [(item['signatures_collected'], item['signatures_required']) for item in pages] == [(0, 1), (0, 2), (1, 1)]


@pytest.mark.parametrize('payload', ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>', '<ScRiPt>alert(1)</ScRiPt>', '&lt;img src=x onerror=alert(1)&gt;'])
@pytest.mark.parametrize('field', ['title', 'reason', 'description', 'signature'])
def test_requisition_and_signature_markup_is_rejected_without_changes(workspace, payload, field):
    client, path = workspace
    login(client, 'manager' if field == 'signature' else 'analyst')
    tables = ('requisitions', 'requisition_lines', 'approvals', 'signatures', 'audit_log', 'notifications')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    if field == 'signature':
        response = client.post('/api/v1/approvals/1/sign', json=signature(reason=payload))
    else:
        body = {'supplier_id': 1, 'title': 'Valid', 'reason': 'Needed supplies', 'lines': [{'description': 'Tubes', 'quantity': 1, 'unit_price': '1.00'}]}
        if field == 'description':
            body['lines'][0]['description'] = payload
        else:
            body[field] = payload
        response = client.post('/api/v1/requisitions', json=body)
    assert response.status_code == 422
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before


def test_legitimate_requisition_and_signature_text_is_preserved(workspace):
    client, path = workspace
    login(client, 'analyst')
    body = {'supplier_id': 1, 'title': 'R&D < 5 units', 'reason': 'A & B supplies', 'lines': [{'description': 'Tubes > 2 mm & caps', 'quantity': 1, 'unit_price': '1.00'}]}
    response = client.post('/api/v1/requisitions', json=body)
    assert response.status_code == 201
    rid = response.json()['id']
    response = client.post(f'/api/v1/requisitions/{rid}/submit')
    assert response.status_code == 200
    aid = response.json()['approval_id']
    login(client, 'manager')
    assert client.post(f'/api/v1/approvals/{aid}/sign', json=signature(reason='Reviewed A & B < 10')).status_code == 200
    with connect(path) as db:
        assert db.execute('SELECT title, reason FROM requisitions WHERE id=?', (rid,)).fetchone()[:] == (body['title'], body['reason'])
        assert db.execute('SELECT description FROM requisition_lines WHERE requisition_id=?', (rid,)).fetchone()[0] == body['lines'][0]['description']
        assert db.execute('SELECT reason FROM signatures WHERE approval_id=?', (aid,)).fetchone()[0] == 'Reviewed A & B < 10'


@pytest.mark.parametrize('change', [
    {'supplier_id': None}, {'title': None}, {'lines': None},
    {'supplier_id': '1'}, {'title': 12}, {'lines': {}},
    {'title': 'x' * 301}, {'reason': 'x' * 301},
    {'lines': [{'description': 'x', 'quantity': '1', 'unit_price': '1'}]},
])
def test_invalid_requisition_input_does_not_mutate_state(workspace, change):
    client, path = workspace
    login(client, 'analyst')
    body = {'supplier_id': 1, 'title': 'Valid', 'reason': 'Needed', 'lines': [{'description': 'Tubes', 'quantity': 1, 'unit_price': '1'}]}
    with connect(path) as db:
        before = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('requisitions', 'requisition_lines', 'approvals', 'audit_log', 'notifications')]
    response = client.post('/api/v1/requisitions', json={**body, **change})
    assert response.status_code == 422
    with connect(path) as db:
        assert [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('requisitions', 'requisition_lines', 'approvals', 'audit_log', 'notifications')] == before


@pytest.mark.parametrize('field', ['supplier_id', 'title', 'reason', 'lines'])
def test_missing_requisition_field_does_not_create_draft(workspace, field):
    client, path = workspace
    login(client, 'analyst')
    body = {'supplier_id': 1, 'title': 'Valid', 'reason': 'Needed', 'lines': [{'description': 'Tubes', 'quantity': 1, 'unit_price': '1'}]}
    del body[field]
    with connect(path) as db:
        before = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('requisitions', 'requisition_lines', 'approvals', 'audit_log')]
    assert client.post('/api/v1/requisitions', json=body).status_code == 422
    with connect(path) as db:
        assert [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('requisitions', 'requisition_lines', 'approvals', 'audit_log')] == before


@pytest.mark.parametrize('field', ['description', 'quantity', 'unit_price'])
def test_missing_requisition_line_field_preserves_state(workspace, field):
    client, path = workspace
    login(client, 'analyst')
    body = {'supplier_id': 1, 'title': 'Valid', 'reason': 'Needed', 'lines': [{'description': 'Tubes', 'quantity': 1, 'unit_price': '1'}]}
    del body['lines'][0][field]
    tables = ('requisitions', 'requisition_lines', 'approvals', 'signatures', 'audit_log', 'notifications')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    response = client.post('/api/v1/requisitions', json=body)
    assert response.status_code == 422
    assert any(error['loc'] == ['body', 'lines', 0, field] and error['type'] == 'missing' for error in response.json()['detail'])
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before


@pytest.mark.parametrize('body', [
    {'reason': 'Reviewed carefully', 'password': 'Demo@1234'},
    {'meaning': 'Approved', 'password': 'Demo@1234'},
    {'meaning': 'Approved', 'reason': 'Reviewed carefully'},
    {'meaning': 1, 'reason': 'Reviewed carefully', 'password': 'Demo@1234'},
    {'meaning': 'Approved', 'reason': [], 'password': 'Demo@1234'},
    {'meaning': 'Approved', 'reason': 'x' * 1001, 'password': 'Demo@1234'},
    {'meaning': 'Approved', 'reason': 'Reviewed carefully', 'password': 'x' * 73},
])
def test_invalid_signature_preserves_all_decision_state(workspace, body):
    client, path = workspace
    login(client, 'manager')
    tables = ('approvals', 'signatures', 'requisitions', 'audit_log', 'notifications')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in tables}
    assert client.post('/api/v1/approvals/1/sign', json=body).status_code == 422
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in tables}
    assert after == before


@pytest.mark.parametrize('values,error', [
    ((999999, 3, 'Approved', 'Reviewed carefully', '2026-01-01'), 'FOREIGN KEY constraint failed'),
    ((1, 999999, 'Approved', 'Reviewed carefully', '2026-01-01'), 'FOREIGN KEY constraint failed'),
    ((1, 3, 'Approved', None, '2026-01-01'), 'NOT NULL constraint failed: signatures.reason'),
    ((3, 3, 'Approved', 'Reviewed carefully', '2026-01-01'), 'UNIQUE constraint failed: signatures.approval_id, signatures.signer_id'),
])
def test_sqlite_signature_constraints_roll_back_transaction(workspace, values, error):
    _, path = workspace
    with connect(path) as db:
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        before = [tuple(row) for row in db.execute('SELECT * FROM signatures ORDER BY id')]
        old_title = db.execute('SELECT title FROM approvals WHERE id=1').fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match=error):
            with db:
                db.execute("UPDATE approvals SET title='transaction marker' WHERE id=1")
                db.execute('INSERT INTO signatures (approval_id,signer_id,meaning,reason,signed_at) VALUES (?,?,?,?,?)', values)
        assert db.execute('SELECT title FROM approvals WHERE id=1').fetchone()[0] == old_title
        assert [tuple(row) for row in db.execute('SELECT * FROM signatures ORDER BY id')] == before


def test_other_analyst_cannot_submit_an_owned_draft(workspace):
    client, path = workspace
    login(client, 'analyst')
    rid = draft(client)
    with connect(path) as db:
        db.execute("INSERT INTO users (email,password_hash,role,display_name,status) SELECT 'other@procurem.demo',password_hash,'analyst','Other Analyst','active' FROM users WHERE id=1")
    response = client.post('/api/v1/auth/login', json={'email': 'other@procurem.demo', 'password': 'Demo@1234'})
    assert response.status_code == 200
    tables = ('requisitions', 'requisition_lines', 'approvals', 'signatures', 'audit_log', 'notifications')
    with connect(path) as db:
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    response = client.post(f'/api/v1/requisitions/{rid}/submit')
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before
    assert response.status_code == 403


@pytest.mark.parametrize('corruption', ['empty', 'zero_quantity', 'negative_price', 'invalid_price'])
def test_submit_invalid_stored_lines_rejects_without_mutation(workspace, corruption):
    client, path = workspace
    login(client, 'analyst')
    rid = draft(client)
    with connect(path) as db:
        if corruption == 'empty':
            db.execute('DELETE FROM requisition_lines WHERE requisition_id=?', (rid,))
        elif corruption == 'zero_quantity':
            db.execute('UPDATE requisition_lines SET quantity=0 WHERE requisition_id=?', (rid,))
        elif corruption == 'negative_price':
            db.execute("UPDATE requisition_lines SET unit_price='-1' WHERE requisition_id=?", (rid,))
        else:
            db.execute("UPDATE requisition_lines SET unit_price='not-a-price' WHERE requisition_id=?", (rid,))
        tables = ('requisitions', 'requisition_lines', 'approvals', 'signatures', 'audit_log', 'notifications')
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    error_client = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    try:
        response = error_client.post(f'/api/v1/requisitions/{rid}/submit')
    finally:
        error_client.close()
    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    assert after == before
    assert response.status_code == 422
