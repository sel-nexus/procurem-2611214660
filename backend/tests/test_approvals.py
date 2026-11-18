"""Exercise approvals against isolated seeded file-backed SQLite databases."""
from pathlib import Path
from tempfile import TemporaryDirectory
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
    submitted = client.post(f'/api/v1/requisitions/{rid}/submit').json()
    aid = submitted['approval_id']
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
    aid = client.post(f'/api/v1/requisitions/{rid}/submit').json()['approval_id']
    assert client.get(f'/api/v1/approvals/{aid}').json()['risk'] == 'high'
    login(client,'compliance')
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code == 403
    login(client,'manager')
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).json()['status'] == 'pending_second'
    with connect(path) as db:
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(rid,)).fetchone()[0] == 'pending_approval'
        assert db.execute('SELECT count(*) FROM notifications WHERE user_id=6 AND link=?',(f'/approvals/{aid}',)).fetchone()[0] == 1
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature()).status_code == 403
    login(client,'compliance')
    assert client.post(f'/api/v1/approvals/{aid}/sign',json=signature('Rejected')).json()['status'] == 'rejected'
    with connect(path) as db:
        assert db.execute('SELECT status FROM requisitions WHERE id=?',(rid,)).fetchone()[0] == 'rejected'
        assert db.execute('SELECT count(*) FROM signatures WHERE approval_id=?',(aid,)).fetchone()[0] == 2

def test_seeded_award_requires_two_and_applies_once(workspace):
    client,path = workspace
    login(client,'sourcing')
    assert client.post('/api/v1/approvals/2/sign',json=signature()).status_code == 403
    login(client,'manager')
    assert client.post('/api/v1/approvals/2/sign',json=signature()).json()['status'] == 'pending_second'
    with connect(path) as db:
        assert db.execute('SELECT status,winning_supplier_id FROM sourcing_events WHERE id=1').fetchone()[:] == ('active',None)
    login(client,'compliance')
    assert client.post('/api/v1/approvals/2/sign',json=signature()).json()['status'] == 'approved'
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
    aid = client.post(f'/api/v1/requisitions/{rid}/submit').json()['approval_id']
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
    high_approval = client.post(f'/api/v1/requisitions/{high_id}/submit').json()['approval_id']
    low_id = draft(client, '4999.99')
    low_approval = client.post(f'/api/v1/requisitions/{low_id}/submit').json()['approval_id']
    assert client.get(f'/api/v1/approvals/{low_approval}').json()['risk'] == 'low'
    login(client, 'manager')
    assert client.post(f'/api/v1/approvals/{high_approval}/sign', json=signature()).json()['status'] == 'pending_second'
    assert client.post(f'/api/v1/approvals/{low_approval}/sign', json=signature('Rejected')).json()['status'] == 'rejected'
    login(client, 'compliance')
    assert client.post(f'/api/v1/approvals/{high_approval}/sign', json=signature()).json()['status'] == 'approved'
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
