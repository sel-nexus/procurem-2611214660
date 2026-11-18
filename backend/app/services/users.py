"""Maintain accounts and their session state atomically."""
import secrets
import sqlite3
from fastapi import HTTPException
from app.core.security import hash_password
from app.schemas.users import CreateUser, UpdateUser
from app.services.auth import now

FIELDS = 'id, display_name, email, role, status'
SORTS = {'display_name', 'email', 'role', 'status'}

def get_user(db: sqlite3.Connection, user_id: int) -> dict:
    """Return public account fields or report a missing account."""
    row = db.execute(f'SELECT {FIELDS} FROM users WHERE id=?', (user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'User not found.')
    return dict(row)

def list_users(db: sqlite3.Connection, search: str, page: int, page_size: int, sort: str, order: str) -> dict:
    """Search and sort a page without interpolating untrusted SQL."""
    if sort not in SORTS or order not in ('asc', 'desc'):
        raise HTTPException(422, 'Invalid sort or order.')
    term = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    where = " WHERE display_name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\'"
    total = db.execute('SELECT count(*) FROM users' + where, (term, term)).fetchone()[0]
    rows = db.execute(f'SELECT {FIELDS} FROM users' + where + f' ORDER BY {sort} COLLATE NOCASE {order.upper()}, id ASC LIMIT ? OFFSET ?', (term, term, page_size, (page-1)*page_size)).fetchall()
    return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}

def _begin_admin(db: sqlite3.Connection, actor_id: int) -> sqlite3.Row:
    """Lock the write transaction and recheck the actor's current privileges."""
    db.execute('BEGIN IMMEDIATE')
    actor = db.execute('SELECT * FROM users WHERE id=?', (actor_id,)).fetchone()
    if not actor or actor['role'] != 'admin' or actor['status'] != 'active':
        raise HTTPException(403, 'Permission denied.')
    return actor

def _audit(db: sqlite3.Connection, actor: sqlite3.Row, action: str, target: int, detail: str) -> None:
    """Append a credential-free audit record in the current transaction."""
    db.execute('INSERT INTO audit_log (user_id,role,action,record_type,record_id,detail,created_at) VALUES (?,?,?,?,?,?,?)', (actor['id'], actor['role'], action, 'user', str(target), detail, now().isoformat()))

def create_user(db: sqlite3.Connection, actor_id: int, body: CreateUser) -> dict:
    """Create an active account, preferences and audit entry together."""
    password = secrets.token_urlsafe(24)
    password_hash = hash_password(password)
    try:
        with db:
            actor = _begin_admin(db, actor_id)
            cursor = db.execute('INSERT INTO users (email,password_hash,role,display_name,status) VALUES (?,?,?,?,?)', (body.email, password_hash, body.role, body.display_name, 'active'))
            user_id = cursor.lastrowid
            db.execute('INSERT INTO user_preferences (user_id) VALUES (?)', (user_id,))
            _audit(db, actor, 'create_user', user_id, 'Created user')
            record = get_user(db, user_id)
    except sqlite3.IntegrityError as exc:
        if 'users.email' in str(exc):
            raise HTTPException(409, 'Email is already in use.') from exc
        raise
    return {'user': record, 'temporary_password': password}

def update_user(db: sqlite3.Connection, actor_id: int, user_id: int, body: UpdateUser) -> dict:
    """Update editable fields and revoke sessions upon deactivation."""
    with db:
        actor = _begin_admin(db, actor_id)
        previous = get_user(db, user_id)
        if actor_id == user_id and (body.status != 'active' or body.role != 'admin'):
            raise HTTPException(403, 'You cannot deactivate or remove your own admin role.')
        db.execute('UPDATE users SET display_name=?, role=?, status=? WHERE id=?', (body.display_name, body.role, body.status, user_id))
        if body.status == 'inactive':
            db.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (now().isoformat(), user_id))
        action = 'deactivate_user' if previous['status'] != 'inactive' and body.status == 'inactive' else 'update_user'
        _audit(db, actor, action, user_id, 'Updated user account')
        result = get_user(db, user_id)
    return result

def reset_password(db: sqlite3.Connection, actor_id: int, user_id: int) -> dict:
    """Replace the password hash and revoke all existing sessions atomically."""
    password = secrets.token_urlsafe(24)
    password_hash = hash_password(password)
    with db:
        actor = _begin_admin(db, actor_id)
        record = get_user(db, user_id)
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash, user_id))
        db.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (now().isoformat(), user_id))
        _audit(db, actor, 'update_user', user_id, 'Reset user password')
    return {'user': record, 'temporary_password': password}
