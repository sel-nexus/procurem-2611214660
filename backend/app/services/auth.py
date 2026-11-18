"""Authenticate users and manage persistent, revocable sessions."""
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.core.security import hash_password, verify_password, new_token, token_hash

# A dummy hash makes unknown accounts do the same password work.
DUMMY_HASH = hash_password('not-a-real-password')

def now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)

def login(db: sqlite3.Connection, email: str, password: str, remember: bool) -> tuple[sqlite3.Row, str, int]:
    """Validate credentials and persist a new session or reject them."""
    user = db.execute('SELECT * FROM users WHERE email = ?', (email.strip(),)).fetchone()
    valid = verify_password(password, user['password_hash'] if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, 'Authentication failed. Please check your credentials.')
    if user['status'] != 'active':
        raise HTTPException(401, 'This account is inactive.')
    token = new_token()
    seconds = 30 * 24 * 3600 if remember else 8 * 3600
    db.execute('INSERT INTO sessions VALUES (?,?,?,NULL)', (token_hash(token), user['id'], (now()+timedelta(seconds=seconds)).isoformat()))
    db.execute('INSERT INTO audit_log (user_id,role,action,record_type,record_id,detail,created_at) VALUES (?,?,?,?,?,?,?)', (user['id'],user['role'],'sign_in','user',str(user['id']),'Signed in',now().isoformat()))
    db.commit()
    return user, token, seconds

def current_user(db: sqlite3.Connection, token: str | None) -> sqlite3.Row:
    """Resolve a valid, active, unexpired session or reject it."""
    if token:
        row = db.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status=?', (token_hash(token),now().isoformat(),'active')).fetchone()
        if row:
            return row
    raise HTTPException(401, 'Session expired or not authenticated.')

def logout(db: sqlite3.Connection, token: str) -> None:
    """Revoke a session so a copied cookie cannot be reused."""
    db.execute('UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL',(now().isoformat(),token_hash(token)))
    db.commit()
