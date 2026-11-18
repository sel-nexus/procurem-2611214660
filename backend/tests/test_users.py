"""Exercise account administration against a file-backed SQLite database."""
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.database import connect
from app.core.security import verify_password
from app.main import create_app
from app.schemas.users import CreateUser, UpdateUser
from app.services import users

@pytest.fixture
def workspace():
    """Start a seeded API backed by an isolated file."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'users.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            yield client, path

def login(client, email, password):
    """Authenticate through the public endpoint."""
    return client.post('/api/v1/auth/login', json={'email':email, 'password':password})

def admin(client):
    """Sign in as the seeded administrator."""
    response = login(client, 'admin@procurem.demo', 'Admin@5678')
    assert response.status_code == 200
    return response.json()['id']

def test_create_search_pagination_and_database_state(workspace):
    client, path = workspace
    admin(client)
    response = client.post('/api/v1/users', json={'display_name':'  Alice Example  ','email':'Alice@Example.com','role':'analyst'})
    assert response.status_code == 201 and response.headers['cache-control'] == 'no-store'
    result = response.json(); account = result['user']; password = result['temporary_password']
    assert account['email'] == 'alice@example.com' and account['status'] == 'active'
    assert account['display_name'] == 'Alice Example' and len(password) >= 24
    assert client.post('/api/v1/users', json={'display_name':'Duplicate','email':'ALICE@example.com','role':'admin'}).status_code == 409
    found = client.get('/api/v1/users', params={'search':'example.com','page_size':1,'sort':'email','order':'desc'}).json()
    assert found['total'] == 1 and found['items'] == [account]
    assert client.get('/api/v1/users?search=%25').json()['total'] == 0
    assert client.get('/api/v1/users?page_size=101').status_code == 422
    assert client.get('/api/v1/users?sort=password_hash').status_code == 422
    assert client.get('/api/v1/users?order=sideways').status_code == 422
    with connect(path) as db:
        stored = db.execute('SELECT * FROM users WHERE id=?',(account['id'],)).fetchone()
        assert stored['password_hash'] != password and verify_password(password, stored['password_hash'])
        assert db.execute('SELECT user_id FROM user_preferences WHERE user_id=?',(account['id'],)).fetchone()
        assert password not in str([tuple(row) for row in db.execute('SELECT * FROM audit_log')])
    assert login(client, account['email'], password).status_code == 200

def test_reset_revokes_all_sessions_and_deactivate_denies_signin(workspace):
    client, path = workspace
    admin(client)
    result = client.post('/api/v1/users',json={'display_name':'New User','email':'new@example.com','role':'analyst'}).json()
    uid = result['user']['id']; old = result['temporary_password']
    app = client.app
    with TestClient(app) as other:
        assert login(other,'new@example.com',old).status_code == 200
        reset = client.post(f'/api/v1/users/{uid}/reset-password')
        assert reset.status_code == 200 and reset.headers['cache-control'] == 'no-store'
        new = reset.json()['temporary_password']; assert new != old
        assert other.get('/api/v1/auth/me').status_code == 401
        assert login(other,'new@example.com',old).status_code == 401
        assert login(other,'new@example.com',new).status_code == 200
        updated = client.put(f'/api/v1/users/{uid}',json={'display_name':'Renamed','role':'finance_analyst','status':'inactive'})
        assert updated.status_code == 200 and updated.json()['display_name'] == 'Renamed'
        assert other.get('/api/v1/auth/me').status_code == 401
        inactive = login(other,'new@example.com',new)
        assert inactive.status_code == 401 and inactive.json()['detail'] == 'This account is inactive.'
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM users WHERE id=?',(uid,)).fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM sessions WHERE user_id=? AND revoked_at IS NULL',(uid,)).fetchone()[0] == 0
        audit = str([tuple(row) for row in db.execute('SELECT * FROM audit_log')])
        assert old not in audit and new not in audit and 'deactivate_user' in audit

def test_permissions_self_protection_and_validation(workspace):
    client, _ = workspace
    paths = ['/api/v1/users','/api/v1/users/1']
    assert all(client.get(path).status_code == 401 for path in paths)
    for email in ['analyst','category.mgr','proc.manager','sourcing','finance','compliance']:
        assert login(client, email+'@procurem.demo','Demo@1234').status_code == 200
        assert all(client.get(path).status_code == 403 for path in paths)
        assert client.post('/api/v1/users',json={'display_name':'x','email':'x@example.com','role':'analyst'}).status_code == 403
        assert client.put('/api/v1/users/1',json={'display_name':'x','role':'analyst','status':'active'}).status_code == 403
        assert client.post('/api/v1/users/1/reset-password').status_code == 403
    uid = admin(client)
    for role,status in [('admin','inactive'),('analyst','active')]:
        assert client.put(f'/api/v1/users/{uid}',json={'display_name':'Helen','role':role,'status':status}).status_code == 403
    assert client.get('/api/v1/users/99999').status_code == 404
    assert client.post('/api/v1/users/99999/reset-password').status_code == 404
    assert client.put('/api/v1/users/99999',json={'display_name':'x','role':'analyst','status':'active'}).status_code == 404
    assert client.delete('/api/v1/users/1').status_code == 405
    for payload in [{'display_name':' ','email':'a@example.com','role':'admin'}, {'display_name':'A','email':'bad','role':'admin'}, {'display_name':'A','email':'a@example.com','role':'root'}, {'display_name':'A','email':'a@example.com','role':'admin','password':'injected'}]:
        assert client.post('/api/v1/users',json=payload).status_code == 422
    assert client.put('/api/v1/users/1',json={'display_name':'x','role':'admin','status':'active','email':'changed@example.com'}).status_code == 422

def test_services_recheck_admin_and_rollback(workspace):
    _, path = workspace
    with connect(path) as db:
        actor = db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        analyst = db.execute("SELECT id FROM users WHERE role='analyst'").fetchone()[0]
        result = users.create_user(db, actor, CreateUser(display_name='Service',email='service@example.com',role='analyst'))
        uid = result['user']['id']
        assert users.get_user(db, uid)['email'] == 'service@example.com'
        assert users.list_users(db, 'Service',1,20,'display_name','asc')['total'] == 1
        with pytest.raises(HTTPException) as forbidden:
            users.update_user(db, analyst, uid, UpdateUser(display_name='No',role='admin',status='active'))
        assert forbidden.value.status_code == 403 and users.get_user(db, uid)['display_name'] == 'Service'
        with pytest.raises(HTTPException):
            users.reset_password(db, analyst, uid)
        with pytest.raises(HTTPException):
            users.list_users(db,'',1,20,'id; DROP TABLE users','asc')
