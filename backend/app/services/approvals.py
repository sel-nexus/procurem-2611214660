"""Implement atomic requisition submission and approval decisions."""
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from app.core.security import verify_password
from app.schemas.approvals import RequisitionInput, SignatureInput


def now() -> str:
    """Return an unambiguous UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def audit(db: sqlite3.Connection, user: sqlite3.Row, action: str, kind: str, record_id: int, detail: str) -> None:
    """Append an audit entry inside the caller's transaction."""
    db.execute('INSERT INTO audit_log (user_id,role,action,record_type,record_id,detail,created_at) VALUES (?,?,?,?,?,?,?)', (user['id'], user['role'], action, kind, str(record_id), detail, now()))


def notify(db: sqlite3.Connection, user_id: int, title: str, body: str, approval_id: int) -> None:
    """Queue an in-app notification inside the caller's transaction."""
    db.execute('INSERT INTO notifications (user_id,title,body,created_at,link) VALUES (?,?,?,?,?)', (user_id, title, body, now(), f'/approvals/{approval_id}'))


def notify_role(db: sqlite3.Connection, role: str, title: str, approval_id: int) -> None:
    """Notify active users holding the required signing role."""
    for recipient in db.execute("SELECT id FROM users WHERE role=? AND status='active'", (role,)):
        notify(db, recipient['id'], title, 'A request is waiting for your review.', approval_id)


def create_draft(db: sqlite3.Connection, user: sqlite3.Row, body: RequisitionInput) -> dict:
    """Create a validated analyst-owned draft and its lines atomically."""
    if user['role'] != 'analyst':
        raise HTTPException(403, 'Permission denied.')
    db.execute('BEGIN IMMEDIATE')
    try:
        if not db.execute('SELECT 1 FROM suppliers WHERE id=?', (body.supplier_id,)).fetchone():
            raise HTTPException(422, 'Supplier is required.')
        total = sum((line.unit_price * line.quantity for line in body.lines), Decimal('0'))
        code_number = db.execute("SELECT COALESCE(MAX(CAST(SUBSTR(code,5) AS INTEGER)),2000)+1 FROM requisitions WHERE code GLOB 'REQ-[0-9]*'").fetchone()[0]
        cursor = db.execute('INSERT INTO requisitions (code,supplier_id,title,total_amount_usd,status,requester_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?)', (f'REQ-{code_number}', body.supplier_id, body.title, str(total), 'draft', user['id'], body.reason, now()))
        record_id = cursor.lastrowid
        db.executemany('INSERT INTO requisition_lines (requisition_id,description,quantity,unit_price) VALUES (?,?,?,?)', [(record_id, line.description, line.quantity, str(line.unit_price)) for line in body.lines])
        audit(db, user, 'create_requisition', 'requisition', record_id, 'Created requisition draft')
        db.commit()
        return dict(db.execute('SELECT * FROM requisitions WHERE id=?', (record_id,)).fetchone())
    except Exception:
        db.rollback()
        raise


def submit(db: sqlite3.Connection, user: sqlite3.Row, record_id: int) -> dict:
    """Submit an owned draft once and notify the first signers."""
    if user['role'] != 'analyst':
        raise HTTPException(403, 'Permission denied.')
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM requisitions WHERE id=?', (record_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Requisition not found.')
        if row['requester_id'] != user['id']:
            raise HTTPException(403, 'Permission denied.')
        if row['status'] != 'draft':
            raise HTTPException(409, 'Only drafts can be submitted.')
        lines = [dict(line) for line in db.execute('SELECT description,quantity,unit_price FROM requisition_lines WHERE requisition_id=?', (record_id,))]
        total = sum((Decimal(line['unit_price']) * line['quantity'] for line in lines), Decimal('0'))
        if not lines or total <= 0 or any(line['quantity'] <= 0 or Decimal(line['unit_price']) <= 0 for line in lines):
            raise HTTPException(422, 'Amount must be greater than 0.')
        supplier = db.execute('SELECT name FROM suppliers WHERE id=?', (row['supplier_id'],)).fetchone()
        proposed = {'code': row['code'], 'title': row['title'], 'supplier': supplier['name'], 'total_amount_usd': str(total), 'reason': row['reason'], 'lines': lines}
        db.execute("UPDATE requisitions SET status='pending_approval', total_amount_usd=? WHERE id=?", (str(total), record_id))
        cursor = db.execute('INSERT INTO approvals (approval_type,title,subject_table,subject_id,current_json,proposed_json,amount_usd,risk,status,requester_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('requisition', row['title'], 'requisitions', record_id, '{}', json.dumps(proposed), str(total), 'high' if total >= Decimal('10000') else 'low', 'pending', user['id'], row['reason'], now()))
        approval_id = cursor.lastrowid
        audit(db, user, 'submit_requisition', 'requisition', record_id, f'Submitted for approval {approval_id}')
        notify_role(db, 'procurement_manager', 'Requisition awaiting approval', approval_id)
        db.commit()
        return {'id': record_id, 'approval_id': approval_id, 'status': 'pending_approval'}
    except Exception:
        db.rollback()
        raise


def list_approvals(db: sqlite3.Connection, page: int, page_size: int, sort: str, order: str) -> dict:
    """Return a bounded inbox with the number of required signatures."""
    columns = {'id':'a.id','title':'a.title','approval_type':'a.approval_type','requester_name':'u.display_name','amount_usd':'CAST(a.amount_usd AS NUMERIC)','risk':'a.risk','status':'a.status','created_at':'a.created_at','signatures_collected':'(SELECT count(*) FROM signatures s WHERE s.approval_id=a.id)','signatures_required':"CASE WHEN a.risk='high' THEN 2 ELSE 1 END"}
    if sort not in columns:
        raise HTTPException(422, 'Invalid sort field.')
    total = db.execute('SELECT count(*) FROM approvals').fetchone()[0]
    rows = db.execute(f"SELECT a.id,a.approval_type,a.title,a.amount_usd,a.risk,a.status,a.requester_id,u.display_name AS requester_name,(SELECT count(*) FROM signatures s WHERE s.approval_id=a.id) AS signatures_collected,CASE WHEN a.risk='high' THEN 2 ELSE 1 END AS signatures_required FROM approvals a JOIN users u ON u.id=a.requester_id ORDER BY {columns[sort]} {order.upper()},a.id ASC LIMIT ? OFFSET ?", (page_size,(page-1)*page_size)).fetchall()
    return {'items':[dict(row) for row in rows], 'total':total, 'page':page, 'page_size':page_size, 'source_label':'Mock · Approvals', 'freshness':'Real-time'}


def detail(db: sqlite3.Connection, approval_id: int, user: sqlite3.Row) -> dict:
    """Return the proposal, recorded signatures and current user's permission."""
    row = db.execute('SELECT a.*,u.display_name AS requester_name FROM approvals a JOIN users u ON u.id=a.requester_id WHERE a.id=?', (approval_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Approval not found.')
    result = dict(row)
    result['current'] = json.loads(result.pop('current_json'))
    result['proposed'] = json.loads(result.pop('proposed_json'))
    if row['approval_type'] == 'requisition' and set(result['proposed']) == {'status'}:
        requisition = db.execute('SELECT r.code,r.title,r.reason,r.total_amount_usd,s.name AS supplier FROM requisitions r JOIN suppliers s ON s.id=r.supplier_id WHERE r.id=?', (row['subject_id'],)).fetchone()
        if requisition:
            result['proposed'] = {**dict(requisition), **result['proposed'], 'lines': [dict(line) for line in db.execute('SELECT description,quantity,unit_price FROM requisition_lines WHERE requisition_id=?', (row['subject_id'],))]}
    result['signatures'] = [dict(s) for s in db.execute('SELECT s.meaning,s.reason,s.signed_at,s.signer_id,u.display_name,u.role FROM signatures s JOIN users u ON u.id=s.signer_id WHERE s.approval_id=? ORDER BY s.id', (approval_id,))]
    result['signatures_required'] = 2 if row['risk'] == 'high' else 1
    result['can_sign'] = user['id'] != row['requester_id'] and not any(s['signer_id'] == user['id'] for s in result['signatures']) and ((row['status'] == 'pending' and user['role'] == 'procurement_manager') or (row['status'] == 'pending_second' and user['role'] == 'compliance'))
    return result


def apply_decision(db: sqlite3.Connection, row: sqlite3.Row, approved: bool) -> None:
    """Apply a supported subject transition or fail the entire decision."""
    kind, subject, table = row['approval_type'], row['subject_id'], row['subject_table']
    proposed = json.loads(row['proposed_json'])
    if kind == 'requisition' and table == 'requisitions':
        changed = db.execute("UPDATE requisitions SET status=? WHERE id=? AND status='pending_approval'", ('approved' if approved else 'rejected', subject)).rowcount
    elif kind == 'sourcing_award' and table == 'sourcing_events':
        supplier = proposed.get('winning_supplier_id')
        if approved:
            if not isinstance(supplier, int) or not db.execute('SELECT 1 FROM sourcing_bids WHERE event_id=? AND supplier_id=?', (subject,supplier)).fetchone():
                raise HTTPException(409, 'Winning bid is no longer available.')
            changed = db.execute("UPDATE sourcing_events SET status='awarded',winning_supplier_id=? WHERE id=? AND status='active'", (supplier,subject)).rowcount
        else:
            changed = db.execute("SELECT count(*) FROM sourcing_events WHERE id=? AND status='active'", (subject,)).fetchone()[0]
    elif kind == 'sourcing_create' and table == 'sourcing_events':
        changed = db.execute("UPDATE sourcing_events SET status=? WHERE id=? AND status='pending_approval'", ('active' if approved else 'cancelled', subject)).rowcount
    elif kind == 'supplier_edit' and table == 'suppliers':
        allowed = {'contact_name','contact_email','risk','status'}
        if not proposed or not set(proposed).issubset(allowed):
            raise HTTPException(409, 'Invalid supplier proposal.')
        if approved:
            fields = sorted(proposed)
            changed = db.execute('UPDATE suppliers SET ' + ','.join(f'{field}=?' for field in fields) + ' WHERE id=?', [*(proposed[field] for field in fields),subject]).rowcount
        else:
            changed = db.execute('SELECT count(*) FROM suppliers WHERE id=?', (subject,)).fetchone()[0]
    else:
        raise HTTPException(409, 'Unsupported approval subject.')
    if changed != 1:
        raise HTTPException(409, 'Approval subject is no longer in the expected state.')


def sign(db: sqlite3.Connection, user: sqlite3.Row, approval_id: int, body: SignatureInput) -> dict:
    """Serialize signatures and commit the decision and all effects together."""
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM approvals WHERE id=?', (approval_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Approval not found.')
        allowed = (row['status'] == 'pending' and user['role'] == 'procurement_manager') or (row['status'] == 'pending_second' and user['role'] == 'compliance')
        if not allowed or row['requester_id'] == user['id'] or db.execute('SELECT 1 FROM signatures WHERE approval_id=? AND signer_id=?', (approval_id,user['id'])).fetchone():
            raise HTTPException(403, 'Permission denied.')
        if not verify_password(body.password, user['password_hash']):
            raise HTTPException(422, 'Password does not match. The signature was not saved.')
        stamp = now()
        final = body.meaning == 'Rejected' or row['risk'] == 'low' or row['status'] == 'pending_second'
        if final:
            apply_decision(db, row, body.meaning == 'Approved')
        db.execute('INSERT INTO signatures (approval_id,signer_id,meaning,reason,signed_at) VALUES (?,?,?,?,?)', (approval_id,user['id'],body.meaning,body.reason,stamp))
        status = ('approved' if body.meaning == 'Approved' else 'rejected') if final else 'pending_second'
        db.execute('UPDATE approvals SET status=?,decided_at=? WHERE id=?', (status,stamp if final else None,approval_id))
        audit(db,user,'sign','approval',approval_id,f'{body.meaning} approval {approval_id}')
        if final:
            notify(db,row['requester_id'],'Approval decided',f'Your request was {status}.',approval_id)
        else:
            notify_role(db,'compliance','Approval awaiting second signature',approval_id)
        db.commit()
        return detail(db,approval_id,user)
    except Exception:
        db.rollback()
        raise
