"""Provide private workspace data and read-only administrative views."""
import csv
import io
import sqlite3
from fastapi import HTTPException

ROLES = ['analyst', 'category_manager', 'procurement_manager', 'sourcing_specialist', 'finance_analyst', 'compliance', 'admin']
ACTIONS = [
    ('Read procurement records', ROLES),
    ('Read authorized knowledge documents', ROLES),
    ('Create and submit requisitions', ['analyst']),
    ('Propose supplier edits', ['category_manager', 'sourcing_specialist']),
    ('Create sourcing events', ['category_manager', 'sourcing_specialist']),
    ('Request sourcing awards', ['category_manager', 'sourcing_specialist']),
    ('Approve or reject pending items (except own)', ['procurement_manager']),
    ('Second-sign pending items (except own)', ['compliance']),
    ('Read and export audit log', ['procurement_manager', 'compliance', 'admin']),
    ('Open role directory', ['compliance', 'admin']),
    ('Manage users (admin self-protection applies)', ['admin']),
]


def matrix() -> dict:
    """Return the shared permission matrix."""
    return {'actions': [name for name, _ in ACTIONS], 'roles': [{'role': role, 'permissions': [role in allowed for _, allowed in ACTIONS]} for role in ROLES], 'note': 'Knowledge access is restricted by document; signers cannot sign their own requests.'}


def settings(db: sqlite3.Connection, user: sqlite3.Row) -> dict:
    """Read the caller's profile and saved memory."""
    pref = db.execute('SELECT preferred_fiscal_year FROM user_preferences WHERE user_id=?', (user['id'],)).fetchone()
    suppliers = db.execute('SELECT s.id,s.code,s.name FROM frequent_suppliers f JOIN suppliers s ON s.id=f.supplier_id WHERE f.user_id=? ORDER BY s.name', (user['id'],)).fetchall()
    return {'profile': {key: user[key] for key in ('id', 'display_name', 'email', 'role')}, 'preferred_fiscal_year': pref[0] if pref else None, 'frequent_suppliers': [dict(row) for row in suppliers], 'matrix': matrix()}


def save_year(db: sqlite3.Connection, user_id: int, year: int | None) -> None:
    """Persist a fiscal year for the caller."""
    db.execute('INSERT INTO user_preferences (user_id,preferred_fiscal_year) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET preferred_fiscal_year=excluded.preferred_fiscal_year', (user_id, year))
    db.commit()


def remove_supplier(db: sqlite3.Connection, user_id: int, supplier_id: int) -> None:
    """Remove only the caller's saved supplier association."""
    cursor = db.execute('DELETE FROM frequent_suppliers WHERE user_id=? AND supplier_id=?', (user_id, supplier_id))
    if not cursor.rowcount:
        raise HTTPException(404, 'Saved supplier not found.')
    db.commit()


def clear_history(db: sqlite3.Connection, user_id: int) -> None:
    """Remove the caller's messages and conversations in one transaction."""
    with db:
        db.execute('DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)', (user_id,))
        db.execute('DELETE FROM conversations WHERE user_id=?', (user_id,))


def notifications(db: sqlite3.Connection, user_id: int, page: int, page_size: int) -> dict:
    """Return a bounded page of the caller's notifications."""
    total = db.execute('SELECT count(*) FROM notifications WHERE user_id=?', (user_id,)).fetchone()[0]
    rows = db.execute('SELECT id,title,body,created_at,is_read,link FROM notifications WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (user_id, page_size, (page-1)*page_size)).fetchall()
    return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


def unread_count(db: sqlite3.Connection, user_id: int) -> int:
    """Count only unread notifications belonging to the caller."""
    return db.execute('SELECT count(*) FROM notifications WHERE user_id=? AND is_read=0', (user_id,)).fetchone()[0]


def mark_read(db: sqlite3.Connection, user_id: int, notification_id: int) -> dict:
    """Mark an owned notification read or hide its existence."""
    row = db.execute('SELECT id,title,body,created_at,is_read,link FROM notifications WHERE id=? AND user_id=?', (notification_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Notification not found.')
    db.execute('UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?', (notification_id, user_id))
    db.commit()
    return {**dict(row), 'is_read': 1}


def audit(db: sqlite3.Connection, user_id: int | None, action: str, from_date: str | None, to_date: str | None, page: int | None, page_size: int, sort: str, order: str) -> dict:
    """Filter audit rows with bound inputs and stable ordering."""
    columns = {'created_at': 'a.created_at', 'user': 'u.display_name', 'action': 'a.action', 'role': 'a.role', 'record_type': 'a.record_type', 'record_id': 'a.record_id'}
    if sort not in columns:
        raise HTTPException(422, 'Invalid sort field.')
    clauses, values = [], []
    if user_id is not None:
        clauses.append('a.user_id=?'); values.append(user_id)
    if action:
        clauses.append('a.action=?'); values.append(action)
    if from_date:
        clauses.append('substr(a.created_at,1,10)>=?'); values.append(from_date)
    if to_date:
        clauses.append('substr(a.created_at,1,10)<=?'); values.append(to_date)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    source = ' FROM audit_log a LEFT JOIN users u ON u.id=a.user_id'
    total = db.execute('SELECT count(*)' + source + where, values).fetchone()[0]
    sql = 'SELECT a.id,a.user_id,COALESCE(u.display_name,\'System\') AS display_name,a.role,a.action,a.record_type,a.record_id,a.detail,a.created_at' + source + where + f' ORDER BY {columns[sort]} {order.upper()}, a.id DESC'
    if page is not None:
        sql += ' LIMIT ? OFFSET ?'; values += [page_size, (page-1)*page_size]
    return {'items': [dict(row) for row in db.execute(sql, values)], 'total': total, 'page': page, 'page_size': page_size}


def audit_csv(items: list[dict]) -> str:
    """Serialize audit rows safely for spreadsheet consumers."""
    columns = ['created_at', 'display_name', 'role', 'action', 'record_type', 'record_id', 'detail']
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(columns)
    for item in items:
        values = [str(item.get(key) or '') for key in columns]
        writer.writerow(["'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value for value in values])
    return output.getvalue()


def directory(db: sqlite3.Connection, page: int, page_size: int) -> dict:
    """Return a bounded directory without credential fields."""
    total = db.execute('SELECT count(*) FROM users').fetchone()[0]
    rows = db.execute('SELECT id,display_name,email,role,status FROM users ORDER BY display_name COLLATE NOCASE,id LIMIT ? OFFSET ?', (page_size, (page-1)*page_size)).fetchall()
    return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size, 'matrix': matrix()}
