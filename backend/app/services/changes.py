"""Create transactional supplier and sourcing approval requests."""
import json
import sqlite3
from decimal import Decimal
from fastapi import HTTPException
from app.schemas.changes import SupplierEdit, SourcingCreate, AwardInput
from app.services.approvals import audit, notify_role, now


def authorize(user: sqlite3.Row) -> None:
    """Restrict proposals to the two designated roles."""
    if user['role'] not in ('category_manager', 'sourcing_specialist'):
        raise HTTPException(403, 'Permission denied.')


def ensure_no_pending(db: sqlite3.Connection, kind: str, subject: int) -> None:
    """Reject overlapping pending changes to the same subject."""
    if db.execute("SELECT 1 FROM approvals WHERE approval_type=? AND subject_id=? AND status IN ('pending','pending_second')", (kind, subject)).fetchone():
        raise HTTPException(409, 'A proposal is already awaiting a decision for this record.')


def insert_approval(db: sqlite3.Connection, user: sqlite3.Row, kind: str, table: str, subject: int, title: str, current: dict, proposed: dict, amount: Decimal | None, risk: str, action: str) -> int:
    """Persist the approval and its audit and manager notification."""
    cursor = db.execute('INSERT INTO approvals (approval_type,title,subject_table,subject_id,current_json,proposed_json,amount_usd,risk,status,requester_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (kind,title,table,subject,json.dumps(current),json.dumps(proposed),str(amount) if amount is not None else None,risk,'pending',user['id'],'',now()))
    approval_id = cursor.lastrowid
    audit(db,user,action,table,subject,f'Submitted for approval {approval_id}')
    notify_role(db,'procurement_manager','Change awaiting approval',approval_id)
    return approval_id


def supplier_edit(db: sqlite3.Connection, user: sqlite3.Row, subject: int, body: SupplierEdit, *, manage_transaction: bool = True) -> dict:
    """Record a supplier diff, optionally using the caller's transaction."""
    authorize(user)
    if manage_transaction:
        db.execute('BEGIN IMMEDIATE')
    elif not db.in_transaction:
        raise RuntimeError('A caller-managed transaction is required.')
    try:
        row = db.execute('SELECT * FROM suppliers WHERE id=?', (subject,)).fetchone()
        if not row:
            raise HTTPException(404, 'Supplier not found.')
        ensure_no_pending(db,'supplier_edit',subject)
        proposed = body.model_dump(exclude_unset=True)
        current = {key: row[key] for key in proposed}
        if current == proposed:
            raise HTTPException(422, 'The proposal must change at least one field.')
        aid = insert_approval(db,user,'supplier_edit','suppliers',subject,f"Supplier edit: {row['name']}",current,proposed,None,'high' if proposed.get('risk') == 'high' else 'low','propose_supplier_edit')
        if manage_transaction:
            db.commit()
        return {'id':subject,'approval_id':aid,'status':'pending'}
    except Exception:
        if manage_transaction:
            db.rollback()
        raise


def sourcing_create(db: sqlite3.Connection, user: sqlite3.Row, body: SourcingCreate, *, manage_transaction: bool = True) -> dict:
    """Create a pending event, optionally using the caller's transaction."""
    authorize(user)
    if manage_transaction:
        db.execute('BEGIN IMMEDIATE')
    elif not db.in_transaction:
        raise RuntimeError('A caller-managed transaction is required.')
    try:
        code = db.execute("SELECT COALESCE(MAX(CAST(SUBSTR(code,4) AS INTEGER)),3000)+1 FROM sourcing_events WHERE code GLOB 'SE-[0-9]*'").fetchone()[0]
        cursor = db.execute('INSERT INTO sourcing_events (code,title,event_type,status,end_date,estimated_value_usd) VALUES (?,?,?,?,?,?)', (f'SE-{code}',body.title,body.event_type,'pending_approval',body.end_date.isoformat(),str(body.estimated_value_usd)))
        subject = cursor.lastrowid
        proposed = {'code':f'SE-{code}','title':body.title,'event_type':body.event_type,'end_date':body.end_date.isoformat(),'estimated_value_usd':str(body.estimated_value_usd)}
        aid = insert_approval(db,user,'sourcing_create','sourcing_events',subject,body.title,{},proposed,body.estimated_value_usd,'high' if body.estimated_value_usd >= Decimal('10000') else 'low','create_sourcing_event')
        if manage_transaction:
            db.commit()
        return {'id':subject,'approval_id':aid,'status':'pending_approval'}
    except Exception:
        if manage_transaction:
            db.rollback()
        raise


def award(db: sqlite3.Connection, user: sqlite3.Row, subject: int, body: AwardInput, *, manage_transaction: bool = True) -> dict:
    """Request an award, optionally using the caller's transaction."""
    authorize(user)
    if manage_transaction:
        db.execute('BEGIN IMMEDIATE')
    elif not db.in_transaction:
        raise RuntimeError('A caller-managed transaction is required.')
    try:
        event = db.execute('SELECT * FROM sourcing_events WHERE id=?', (subject,)).fetchone()
        if not event:
            raise HTTPException(404, 'Event not found.')
        if event['status'] != 'active':
            raise HTTPException(409, 'Only active events can be awarded.')
        ensure_no_pending(db,'sourcing_award',subject)
        bid = db.execute('SELECT * FROM sourcing_bids WHERE id=? AND event_id=?', (body.bid_id,subject)).fetchone()
        if not bid:
            raise HTTPException(422, 'Choose a bid belonging to this event.')
        amount = Decimal(bid['amount_usd'])
        proposed = {'bid_id':bid['id'],'winning_supplier_id':bid['supplier_id'],'status':'awarded','amount_usd':str(amount)}
        aid = insert_approval(db,user,'sourcing_award','sourcing_events',subject,f"Award: {event['title']}",{'status':event['status'],'winning_supplier_id':event['winning_supplier_id']},proposed,amount,'high' if amount >= Decimal('10000') else 'low','request_award')
        if manage_transaction:
            db.commit()
        return {'id':subject,'approval_id':aid,'status':'pending'}
    except Exception:
        if manage_transaction:
            db.rollback()
        raise
