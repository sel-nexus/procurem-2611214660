"""Exercise authentication and the complete seed using real SQLite files."""
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.database import connect
from app.core.seed import seed_database
from app.core.security import token_hash, verify_password
from app.main import create_app
from app.routers.auth import require_roles

@pytest.fixture
def workspace():
    """Start an isolated application with a persistent guest-local database file."""
    with tempfile.TemporaryDirectory(prefix='procurem-test-', dir=Path.home()) as folder:
        path = str(Path(folder) / 'nested' / 'test.db')
        app = create_app(Settings(database_path=path, seed_on_startup=True))
        @app.get('/role-test')
        def role_test(user=Depends(require_roles('admin'))):
            """Expose a test-only role-protected endpoint."""
            return {'id':user['id']}
        with TestClient(app) as client:
            yield client, path

def sign_in(client, email='analyst@procurem.demo', password='Demo@1234', remember=False):
    """Submit demo credentials."""
    return client.post('/api/v1/auth/login',json={'email':email,'password':password,'remember_me':remember})

def test_login_me_logout_and_revocation(workspace):
    """Persist the identity and reject a copied cookie after sign-out."""
    client, path = workspace
    assert client.get('/api/v1/auth/me').status_code == 401
    response = sign_in(client)
    assert response.status_code == 200 and response.json()['display_name'] == 'Priya Shah'
    cookie = client.cookies['procurem_session']
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    assert 'Max-Age=28800' in response.headers['set-cookie']
    with connect(path) as db:
        assert db.execute('SELECT token_hash FROM sessions').fetchone()[0] == token_hash(cookie)
        assert cookie not in str(db.execute('SELECT * FROM sessions').fetchone())
        assert db.execute("SELECT count(*) FROM audit_log WHERE action='sign_in'").fetchone()[0] == 1
    assert client.get('/api/v1/auth/me').json()['role'] == 'analyst'
    assert client.get('/role-test').status_code == 403
    assert client.post('/api/v1/auth/logout').status_code == 204
    client.cookies.set('procurem_session', cookie)
    assert client.get('/api/v1/auth/me').status_code == 401

def test_remember_admin_and_expiry(workspace):
    """Honor the thirty-day lifetime and expire sessions server-side."""
    client, path = workspace
    response = sign_in(client,'admin@procurem.demo','Admin@5678',True)
    assert response.status_code == 200 and 'Max-Age=2592000' in response.headers['set-cookie']
    assert client.get('/role-test').status_code == 200
    with connect(path) as db:
        expiry = datetime.fromisoformat(db.execute('SELECT expires_at FROM sessions').fetchone()[0])
        assert timedelta(days=29) < expiry - datetime.now(timezone.utc) <= timedelta(days=30)
        db.execute('UPDATE sessions SET expires_at=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    assert client.get('/api/v1/auth/me').status_code == 401
    assert client.post('/api/v1/auth/logout').status_code == 401

def test_invalid_inactive_and_validation(workspace):
    """Reject invalid credentials, inactive users and malformed input."""
    client, path = workspace
    for email,password in [('analyst@procurem.demo','bad'),('nobody@procurem.demo','bad')]:
        response = sign_in(client,email,password)
        assert response.status_code == 401 and response.json()['detail'] == 'Authentication failed. Please check your credentials.'
    with connect(path) as db:
        db.execute("UPDATE users SET status='inactive' WHERE id=1")
    response = sign_in(client)
    assert response.status_code == 401 and response.json()['detail'] == 'This account is inactive.'
    assert client.post('/api/v1/auth/login',json={}).status_code == 422
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0

def test_inactive_user_loses_existing_session(workspace):
    """Deny sessions as soon as the account is deactivated."""
    client,path = workspace
    assert sign_in(client).status_code == 200
    with connect(path) as db:
        db.execute("UPDATE users SET status='inactive' WHERE id=1")
    assert client.get('/api/v1/auth/me').status_code == 401

def test_seed_counts_integrity_and_idempotency(workspace):
    """Verify complete seed, relationships and preservation after reseeding."""
    client,path = workspace
    expected = {'users':7,'user_preferences':7,'suppliers':12,'catalog_items':15,'purchase_orders':24,'po_lines':48,'invoices':16,'contracts':10,'requisitions':8,'requisition_lines':16,'sourcing_events':6,'sourcing_bids':12,'spend_monthly':36,'knowledge_docs':6,'knowledge_access':26,'approvals':3,'signatures':1,'notifications':2,'audit_log':1,'conversations':0,'messages':0,'frequent_suppliers':1}
    with connect(path) as db:
        assert {t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in expected} == expected
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT count(*) FROM purchase_orders p WHERE status='open' AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.po_id=p.id)").fetchone()[0] >= 4
        assert db.execute("SELECT count(*) FROM invoices WHERE status='unmatched' AND po_id IS NULL").fetchone()[0] >= 4
        assert db.execute("SELECT count(*) FROM contracts WHERE status='expiring_soon'").fetchone()[0] >= 2
        assert verify_password('Demo@1234',db.execute('SELECT password_hash FROM users WHERE id=1').fetchone()[0])
        db.execute("UPDATE suppliers SET name='Saved change' WHERE id=1")
        db.commit()
        assert seed_database(db) is False
        assert db.execute('SELECT name FROM suppliers WHERE id=1').fetchone()[0] == 'Saved change'
        assert db.execute('SELECT count(*) FROM audit_log').fetchone()[0] == 1
    response = client.get('/api/health')
    assert response.status_code == 200 and response.json()['status'] == 'ok'
    assert len(response.json()['adapters']) == 5 and all(x['state'] == 'up' for x in response.json()['adapters'])
    with connect(path) as db:
        db.execute('DELETE FROM knowledge_access')
        db.execute('DELETE FROM knowledge_docs')
    assert next(x for x in client.get('/api/health').json()['adapters'] if x['name']=='Knowledge')['state'] == 'empty'

def test_restart_preserves_seed_and_sessions(workspace):
    """Reopen the same file without duplicating rows or dropping sessions."""
    client,path = workspace
    assert sign_in(client).status_code == 200
    cookie = client.cookies['procurem_session']
    app = create_app(Settings(database_path=path))
    with TestClient(app) as restarted:
        restarted.cookies.set('procurem_session',cookie)
        assert restarted.get('/api/v1/auth/me').json()['display_name'] == 'Priya Shah'
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 7
        assert db.execute("SELECT count(*) FROM audit_log WHERE action='seed'").fetchone()[0] == 1

def test_cors_explicit(workspace):
    """Allow only the configured browser origin for credentials."""
    client,_ = workspace
    headers={'Origin':'http://localhost:3000','Access-Control-Request-Method':'POST'}
    response=client.options('/api/v1/auth/login',headers=headers)
    assert response.status_code == 200 and response.headers['access-control-allow-origin'] == 'http://localhost:3000'
    assert response.headers['access-control-allow-credentials'] == 'true'
    headers['Origin']='http://evil.example'
    assert client.options('/api/v1/auth/login',headers=headers).status_code == 400
