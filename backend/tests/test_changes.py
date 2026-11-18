"""Exercise change requests and approval transitions on file-backed SQLite."""
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.database import connect
from app.main import create_app


@pytest.fixture
def workspace():
    """Provide a seeded, isolated workspace."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'changes.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path


def login(client, name):
    """Switch to a seeded account."""
    assert client.post('/api/v1/auth/login', json={'email':f'{name}@procurem.demo','password':'Demo@1234'}).status_code == 200


def sign(client, aid, meaning='Approved'):
    """Submit a password-confirmed decision."""
    return client.post(f'/api/v1/approvals/{aid}/sign', json={'meaning':meaning,'reason':'Reviewed carefully','password':'Demo@1234'})


def test_role_validation_and_atomicity(workspace):
    client, path = workspace
    event = {'title':'New lab RFQ','event_type':'RFQ','estimated_value_usd':'99.99','end_date':'2027-01-01'}
    paths = [('/api/v1/suppliers/1/proposals',{'risk':'high'}),('/api/v1/sourcing',event),('/api/v1/sourcing/1/awards',{'bid_id':1})]
    assert client.post(paths[0][0],json=paths[0][1]).status_code == 401
    for role in ['analyst','proc.manager','finance','compliance']:
        login(client,role)
        for url, body in paths:
            assert client.post(url,json=body).status_code == 403
    login(client,'category.mgr')
    for body in [{},{'risk':'extreme'},{'contact_email':'bad'},{'contact_name':' '},{'risk':None},{'name':'bad'}]:
        assert client.post(paths[0][0],json=body).status_code == 422
    for patch in [{'event_type':'bad'},{'estimated_value_usd':'0'},{'estimated_value_usd':'1.001'},{'estimated_value_usd':'NaN'},{'end_date':'invalid'},{'title':' '}]:
        assert client.post('/api/v1/sourcing',json={**event,**patch}).status_code == 422
    assert client.post('/api/v1/suppliers/9999/proposals',json={'risk':'high'}).status_code == 404
    assert client.post('/api/v1/sourcing/9999/awards',json={'bid_id':1}).status_code == 404
    assert client.post('/api/v1/sourcing/1/awards',json={'bid_id':9999}).status_code == 409  # seeded pending award
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM approvals').fetchone()[0] == 3
        assert db.execute('SELECT count(*) FROM sourcing_events').fetchone()[0] == 6


def test_event_creation_rolls_back_when_notification_fails(workspace):
    client,path = workspace
    login(client,'category.mgr')
    with connect(path) as db:
        db.execute("CREATE TRIGGER reject_new_notifications BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT, 'notification failure'); END")
        before = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('sourcing_events','approvals','audit_log','notifications')]
    with pytest.raises(Exception, match='notification failure'):
        client.post('/api/v1/sourcing',json={'title':'Atomic event','event_type':'RFQ','estimated_value_usd':'1.00','end_date':'2028-01-01'})
    with connect(path) as db:
        after = [db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('sourcing_events','approvals','audit_log','notifications')]
        assert after == before


def test_supplier_low_high_and_conflicts(workspace):
    client,path = workspace
    login(client,'category.mgr')
    with connect(path) as db:
        original = db.execute('SELECT contact_name,risk FROM suppliers WHERE id=1').fetchone()[:]
    response = client.post('/api/v1/suppliers/1/proposals',json={'contact_name':'New contact'})
    assert response.status_code == 201
    aid = response.json()['approval_id']
    response = client.get(f'/api/v1/approvals/{aid}')
    assert response.status_code == 200
    detail = response.json()
    assert detail['risk'] == 'low' and detail['current']['contact_name'] == original[0] and detail['proposed']['contact_name'] == 'New contact'
    assert client.post('/api/v1/suppliers/1/proposals',json={'risk':'high'}).status_code == 409
    with connect(path) as db:
        assert db.execute('SELECT contact_name,risk FROM suppliers WHERE id=1').fetchone()[:] == original
        assert db.execute('SELECT count(*) FROM notifications WHERE user_id=3 AND link=?',(f'/approvals/{aid}',)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit_log WHERE action='propose_supplier_edit'").fetchone()[0] == 1
    login(client,'proc.manager')
    response = sign(client,aid)
    assert response.status_code == 200
    assert response.json()['status'] == 'approved'
    login(client,'sourcing')
    response = client.post('/api/v1/suppliers/1/proposals',json={'risk':'high'})
    assert response.status_code == 201
    high = response.json()['approval_id']
    login(client,'proc.manager')
    response = sign(client,high)
    assert response.status_code == 200
    assert response.json()['status'] == 'pending_second'
    with connect(path) as db:
        assert db.execute('SELECT contact_name,risk FROM suppliers WHERE id=1').fetchone()[:] == ('New contact',original[1])
    login(client,'compliance')
    response = sign(client,high)
    assert response.status_code == 200
    assert response.json()['status'] == 'approved'
    with connect(path) as db:
        assert db.execute('SELECT risk FROM suppliers WHERE id=1').fetchone()[0] == 'high'
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(high,)).fetchone()[0] == 2


def test_event_create_and_rejection(workspace):
    client,path = workspace
    login(client,'sourcing')
    body = {'title':'Event test','event_type':'RFP','estimated_value_usd':'10000.00','end_date':'2028-01-01'}
    response = client.post('/api/v1/sourcing',json=body)
    assert response.status_code == 201
    created = response.json()
    aid, eid = created['approval_id'], created['id']
    with connect(path) as db:
        assert db.execute('SELECT status,estimated_value_usd FROM sourcing_events WHERE id=?',(eid,)).fetchone()[:] == ('pending_approval','10000.00')
    login(client,'proc.manager')
    response = sign(client,aid)
    assert response.status_code == 200
    assert response.json()['status'] == 'pending_second'
    login(client,'compliance')
    response = sign(client,aid)
    assert response.status_code == 200
    assert response.json()['status'] == 'approved'
    with connect(path) as db:
        assert db.execute('SELECT status FROM sourcing_events WHERE id=?',(eid,)).fetchone()[0] == 'active'
    login(client,'category.mgr')
    body['estimated_value_usd'] = '1.01'
    response = client.post('/api/v1/sourcing',json=body)
    assert response.status_code == 201
    rejected = response.json()
    login(client,'proc.manager')
    response = sign(client,rejected['approval_id'],'Rejected')
    assert response.status_code == 200
    assert response.json()['status'] == 'rejected'
    with connect(path) as db:
        assert db.execute('SELECT status FROM sourcing_events WHERE id=?',(rejected['id'],)).fetchone()[0] == 'cancelled'


def test_award_validation_rejection_and_final_approval(workspace):
    client,path = workspace
    with connect(path) as db:
        event = db.execute("SELECT id FROM sourcing_events WHERE status='active' AND id != 1 LIMIT 1").fetchone()[0]
        bid = db.execute('SELECT id,supplier_id,amount_usd FROM sourcing_bids WHERE event_id=? ORDER BY id LIMIT 1',(event,)).fetchone()
        assert bid['amount_usd'] == '5000.00'
        other = db.execute('SELECT id FROM sourcing_bids WHERE event_id != ? LIMIT 1',(event,)).fetchone()[0]
    login(client,'sourcing')
    assert client.post(f'/api/v1/sourcing/{event}/awards',json={'bid_id':other}).status_code == 422
    response = client.post(f'/api/v1/sourcing/{event}/awards',json={'bid_id':bid['id']})
    assert response.status_code == 201
    aid = response.json()['approval_id']
    login(client,'proc.manager')
    response = sign(client,aid,'Rejected')
    assert response.status_code == 200
    assert response.json()['status'] == 'rejected'
    with connect(path) as db:
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=?',(event,)).fetchone()[:] == ('active',None)
    login(client,'category.mgr')
    response = client.post(f'/api/v1/sourcing/{event}/awards',json={'bid_id':bid['id']})
    assert response.status_code == 201
    aid = response.json()['approval_id']
    response = client.get(f'/api/v1/approvals/{aid}')
    assert response.status_code == 200
    detail = response.json()
    assert detail['amount_usd'] == '5000.00'
    assert detail['risk'] == 'low'
    assert detail['signatures_required'] == 1
    login(client,'proc.manager')
    response = sign(client,aid)
    assert response.status_code == 200
    result = response.json()
    assert result['status'] == 'approved'
    assert len(result['signatures']) == 1
    with connect(path) as db:
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=?',(event,)).fetchone()[:] == ('awarded',bid['supplier_id'])
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 1


def test_concurrent_proposals_and_stale_supplier_rollback(workspace):
    client,path = workspace
    login(client,'category.mgr')
    def submit(_):
        return client.post('/api/v1/suppliers/2/proposals',json={'contact_name':'Another name'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit,range(2)))
    assert sorted(r.status_code for r in results) == [201,409]
    aid = next(r.json()['approval_id'] for r in results if r.status_code == 201)
    with connect(path) as db:
        db.execute("UPDATE suppliers SET contact_name='External change' WHERE id=2")
    login(client,'proc.manager')
    assert sign(client,aid).status_code == 409
    with connect(path) as db:
        assert db.execute('SELECT status FROM approvals WHERE id=?',(aid,)).fetchone()[0] == 'pending'
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 0
        assert db.execute('SELECT contact_name FROM suppliers WHERE id=2').fetchone()[0] == 'External change'
    response = sign(client,aid,'Rejected')
    assert response.status_code == 200
    assert response.json()['status'] == 'rejected'


def test_high_award_waits_for_two_signers_and_checks_bid(workspace):
    client,path = workspace
    with connect(path) as db:
        event = db.execute("SELECT id FROM sourcing_events WHERE status='active' AND id != 1 LIMIT 1").fetchone()[0]
        bid = db.execute('SELECT id,supplier_id FROM sourcing_bids WHERE event_id=? LIMIT 1',(event,)).fetchone()
        db.execute('UPDATE sourcing_bids SET amount_usd=? WHERE id=?',('10000.00',bid['id']))
    login(client,'sourcing')
    response = client.post(f'/api/v1/sourcing/{event}/awards',json={'bid_id':bid['id']})
    assert response.status_code == 201
    aid = response.json()['approval_id']
    response = client.get(f'/api/v1/approvals/{aid}')
    assert response.status_code == 200
    assert response.json()['risk'] == 'high'
    login(client,'proc.manager')
    response = sign(client,aid)
    assert response.status_code == 200
    assert response.json()['status'] == 'pending_second'
    with connect(path) as db:
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=?',(event,)).fetchone()[:] == ('active',None)
        db.execute('DELETE FROM sourcing_bids WHERE id=?',(bid['id'],))
    login(client,'compliance')
    assert sign(client,aid).status_code == 409
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 1
        assert db.execute('SELECT status FROM approvals WHERE id=?',(aid,)).fetchone()[0] == 'pending_second'
    response = sign(client,aid,'Rejected')
    assert response.status_code == 200
    assert response.json()['status'] == 'rejected'
    with connect(path) as db:
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=?',(event,)).fetchone()[:] == ('active',None)


def test_sourcing_create_independent_field_validation_and_no_side_effects(workspace):
    client, path = workspace
    login(client, 'sourcing')
    valid = {'title': 'Boundary RFQ', 'event_type': 'RFQ', 'estimated_value_usd': '1.00', 'end_date': '2028-01-01'}
    cases = [{key: value for key, value in valid.items() if key != field} for field in valid]
    for field, value in [
        ('title', None), ('title', []), ('title', ''), ('title', ' '), ('title', 'x' * 301),
        ('event_type', None), ('event_type', []), ('event_type', 'rfq'),
        ('estimated_value_usd', None), ('estimated_value_usd', []), ('estimated_value_usd', 'bad'),
        ('estimated_value_usd', '-0.01'), ('estimated_value_usd', '0'),
        ('estimated_value_usd', '0.001'), ('estimated_value_usd', '1000000000000.00'),
        ('estimated_value_usd', 'Infinity'), ('end_date', None), ('end_date', []),
        ('end_date', '2028-02-30'), ('end_date', 'not-a-date'),
    ]:
        cases.append({**valid, field: value})
    cases.append({**valid, 'unexpected': 'value'})
    tables = ('sourcing_events', 'approvals', 'audit_log', 'notifications')
    with connect(path) as db:
        before = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in tables}
    for body in cases:
        response = client.post('/api/v1/sourcing', json=body)
        assert response.status_code == 422, (body, response.text)
    with connect(path) as db:
        assert {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in tables} == before


@pytest.mark.parametrize('amount,risk', [('0.01', 'low'), ('9999.99', 'low'), ('10000.00', 'high'), ('999999999999.99', 'high')])
def test_sourcing_create_amount_boundaries(workspace, amount, risk):
    client, path = workspace
    login(client, 'sourcing')
    response = client.post('/api/v1/sourcing', json={'title': 'x' * 300, 'event_type': 'Auction', 'estimated_value_usd': amount, 'end_date': '2028-02-29'})
    assert response.status_code == 201
    result = response.json()
    with connect(path) as db:
        assert db.execute('SELECT estimated_value_usd,status FROM sourcing_events WHERE id=?', (result['id'],)).fetchone()[:] == (amount, 'pending_approval')
        assert db.execute('SELECT risk,status FROM approvals WHERE id=?', (result['approval_id'],)).fetchone()[:] == (risk, 'pending')


def test_award_input_validation_independent_of_pending_conflict(workspace):
    client, path = workspace
    login(client, 'sourcing')
    with connect(path) as db:
        event = db.execute("SELECT id FROM sourcing_events WHERE status='active' AND id != 1 LIMIT 1").fetchone()[0]
        before = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('approvals', 'audit_log', 'notifications')}
    for body in [{}, {'bid_id': None}, {'bid_id': '1'}, {'bid_id': True}, {'bid_id': 1.5}, {'bid_id': []}, {'bid_id': 0}, {'bid_id': -1}, {'bid_id': 1, 'extra': 1}]:
        response = client.post(f'/api/v1/sourcing/{event}/awards', json=body)
        assert response.status_code == 422, (body, response.text)
    assert client.post(f'/api/v1/sourcing/{event}/awards', json={'bid_id': 999999}).status_code == 422
    with connect(path) as db:
        assert {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in before} == before
