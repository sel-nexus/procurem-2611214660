"""Answer bounded procurement questions from authorized SQLite rows."""
import csv
from decimal import Decimal
import io
import json
import math
import re
import sqlite3
import time
from fastapi import HTTPException
from app.schemas.assistant import MessageInput
from app.services import approvals, changes, records

INTENTS = {
    'suppliers': r'\b(suppliers?|vendors?)\b',
    'catalog': r'\b(catalog|items?)\b',
    'purchase-orders': r'\b(purchase orders?|orders?|pos?|po-\d+)\b',
    'invoices': r'\b(invoices?|unmatched)\b',
    'contracts': r'\bcontracts?\b',
    'requisitions': r'\brequisitions?\b',
    'sourcing': r'\b(sourcing|rfq|rfp|bids?)\b',
    'spend': r'\b(spend|spending|categor(?:y|ies))\b',
    'knowledge': r'\b(polic(?:y|ies)|sop|knowledge|documents?)\b',
}
TABLES = {'suppliers':'suppliers','catalog':'catalog_items','purchase-orders':'purchase_orders','invoices':'invoices','contracts':'contracts','requisitions':'requisitions','sourcing':'sourcing_events','spend':'spend_monthly','knowledge':'knowledge_docs'}
FOLLOWUPS = ['Show overdue purchase orders', 'Show spend']
AREAS = ['Purchase orders', 'Invoices', 'Requisitions', 'Sourcing events', 'Spend']


def owned(db: sqlite3.Connection, user: sqlite3.Row, conversation_id: int) -> sqlite3.Row:
    """Hide conversations belonging to another user."""
    row = db.execute('SELECT * FROM conversations WHERE id=? AND user_id=?', (conversation_id, user['id'])).fetchone()
    if not row:
        raise HTTPException(404, 'Conversation not found.')
    return row


def safe_answer(db: sqlite3.Connection, user: sqlite3.Row, answer: dict) -> dict:
    """Remove knowledge snapshots no longer accessible to the current role."""
    for section in answer.get('sections', []):
        if section['resource'] == 'knowledge':
            section['rows'] = [row for row in section['rows'] if db.execute('SELECT 1 FROM knowledge_access WHERE doc_id=? AND role=?', (row['id'], user['role'])).fetchone()]
            section['citations'] = [c for c in section['citations'] if any(row['id'] == c['id'] for row in section['rows'])]
    return answer


def history(db: sqlite3.Connection, user: sqlite3.Row, conversation_id: int) -> dict:
    """Return a user's saved thread, rechecking knowledge access."""
    conversation = dict(owned(db, user, conversation_id))
    messages = []
    for row in db.execute('SELECT id,role,content,created_at FROM messages WHERE conversation_id=? ORDER BY id', (conversation_id,)):
        item = dict(row)
        if item['role'] == 'assistant':
            item['answer'] = safe_answer(db, user, json.loads(item.pop('content')))
        messages.append(item)
    return {**conversation, 'messages': messages}


def conversations(db: sqlite3.Connection, user: sqlite3.Row, page: int, page_size: int) -> dict:
    """List only the caller's threads, newest first."""
    total = db.execute('SELECT count(*) FROM conversations WHERE user_id=?', (user['id'],)).fetchone()[0]
    rows = db.execute('SELECT id,title,created_at FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?', (user['id'], page_size, (page-1)*page_size))
    return {'items':[dict(row) for row in rows], 'total':total, 'page':page, 'page_size':page_size}


def clarification(text: str, areas: list[str] | None = None) -> dict:
    """Build a question without claiming any records."""
    return {'text':text, 'sections':[], 'choices':areas or [], 'followups':FOLLOWUPS, 'supplier_code':None}


def perform_action(db: sqlite3.Connection, user: sqlite3.Row, action) -> dict:
    """Delegate complete proposals to existing role-gated approval services."""
    allowed = {'requisition': ('analyst',), 'supplier_edit': ('category_manager','sourcing_specialist'), 'sourcing_create': ('category_manager','sourcing_specialist'), 'sourcing_award': ('category_manager','sourcing_specialist')}
    if user['role'] not in allowed[action.kind]:
        return clarification('Your role is not permitted to start this request.')
    if action.kind == 'requisition':
        body = action.details
        db.execute('BEGIN IMMEDIATE')
        try:
            supplier = db.execute('SELECT name FROM suppliers WHERE id=?', (body.supplier_id,)).fetchone()
            if not supplier:
                raise HTTPException(422, 'Supplier is required.')
            total = sum((line.unit_price * line.quantity for line in body.lines), Decimal('0'))
            number = db.execute("SELECT COALESCE(MAX(CAST(SUBSTR(code,5) AS INTEGER)),2000)+1 FROM requisitions WHERE code GLOB 'REQ-[0-9]*'").fetchone()[0]
            code = f'REQ-{number}'
            subject = db.execute('INSERT INTO requisitions (code,supplier_id,title,total_amount_usd,status,requester_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?)', (code,body.supplier_id,body.title,str(total),'pending_approval',user['id'],body.reason,approvals.now())).lastrowid
            lines = [{'description':line.description,'quantity':line.quantity,'unit_price':str(line.unit_price)} for line in body.lines]
            db.executemany('INSERT INTO requisition_lines (requisition_id,description,quantity,unit_price) VALUES (?,?,?,?)', [(subject,line['description'],line['quantity'],line['unit_price']) for line in lines])
            proposed = {'code':code,'title':body.title,'supplier':supplier['name'],'total_amount_usd':str(total),'reason':body.reason,'lines':lines}
            aid = db.execute('INSERT INTO approvals (approval_type,title,subject_table,subject_id,current_json,proposed_json,amount_usd,risk,status,requester_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('requisition',body.title,'requisitions',subject,'{}',json.dumps(proposed),str(total),'high' if total >= Decimal('10000') else 'low','pending',user['id'],body.reason,approvals.now())).lastrowid
            approvals.audit(db,user,'create_requisition','requisition',subject,'Created requisition')
            approvals.audit(db,user,'submit_requisition','requisition',subject,f'Submitted for approval {aid}')
            approvals.notify_role(db,'procurement_manager','Requisition awaiting approval',aid)
            db.commit()
            result = {'approval_id':aid}
        except Exception:
            db.rollback()
            raise
    elif action.kind == 'supplier_edit':
        result = changes.supplier_edit(db, user, action.supplier_id, action.details)
    elif action.kind == 'sourcing_create':
        result = changes.sourcing_create(db, user, action.details)
    else:
        result = changes.award(db, user, action.event_id, action.details)
    answer = clarification('A pending approval was created and is waiting for the procurement manager.')
    answer['approval_id'] = result['approval_id']
    return answer


def answer_question(db: sqlite3.Connection, user: sqlite3.Row, message: str, previous: dict | None) -> dict:
    """Route recognized intent words to fixed, bounded record lookups."""
    text = message.strip().lower()
    if re.search(r'\b(create|submit|change|edit|update|propose|award|delete|insert|drop|alter)\b', text):
        kind = 'requisition' if 'requisition' in text else 'supplier_edit' if re.search(r'\b(supplier|vendor)\b', text) else 'sourcing_award' if 'award' in text else 'sourcing_create' if re.search(r'\b(sourcing|rfq|rfp|event)\b', text) else None
        allowed = {'requisition': ('analyst',), 'supplier_edit': ('category_manager','sourcing_specialist'), 'sourcing_create': ('category_manager','sourcing_specialist'), 'sourcing_award': ('category_manager','sourcing_specialist')}
        if kind and user['role'] not in allowed[kind]:
            return clarification('Your role is not permitted to start this request.')
        return clarification('Please provide a complete structured proposal before I can request approval; no change has been made.')
    intents = [name for name, pattern in INTENTS.items() if re.search(pattern, text)]
    if 'unmatched' in text and 'purchase-orders' not in intents:
        intents.append('purchase-orders')
    if text.strip(' ?.!') in ('status', 'show me everything', 'everything') or len(intents) > 3:
        return clarification('Which area do you mean?', AREAS)
    suppliers = db.execute('SELECT id,code,name FROM suppliers').fetchall()
    matched = [s for s in suppliers if re.search(r'(?<!\w)' + re.escape(s['name'].lower()) + r'(?!\w)', text) or re.search(r'(?<!\w)' + re.escape(s['code'].lower()) + r'(?!\w)', text)]
    if len(matched) > 1:
        return clarification('Which supplier do you mean?')
    supplier = matched[0] if matched else None
    reference = bool(re.search(r'\b(their|that supplier|those orders|the same supplier)\b', text))
    if reference and not supplier:
        code = previous.get('supplier_code') if previous else None
        supplier = db.execute('SELECT id,code,name FROM suppliers WHERE code=?', (code,)).fetchone() if code else None
        if not supplier:
            return clarification('Which supplier do you mean?')
    if not supplier and re.search(r'\b(?:supplier|vendor)\s+(?:named\s+|called\s+)?[a-z0-9]', text):
        candidate = re.search(r'\b(?:supplier|vendor)\s+(?:named\s+|called\s+)?([a-z0-9][\w -]*)', text)
        if candidate and not re.match(r'(?:and|or|orders?|spend|status|list|details|information|with|risk)\b', candidate.group(1)):
            return clarification('No matching supplier was found.')
    if not supplier:
        prefix = re.search(r'^\s*(?:show\s+)?(.+?)\s+(?:open |overdue )?(?:orders?|purchase orders?)\s+and\s+spend\b', text)
        if prefix and prefix.group(1).strip() not in ('show me', 'the', 'all', 'my', 'purchase', 'open', 'overdue'):
            return clarification('No matching supplier was found.')
    if supplier and not reference and 'suppliers' not in intents:
        intents.insert(0, 'suppliers')
    if len(intents) > 3:
        return clarification('Which area do you mean?', AREAS)
    if not intents:
        return clarification('I can answer questions about suppliers, catalog, purchase orders, invoices, contracts, requisitions, sourcing, spend and knowledge.')
    sections = []
    year_row = db.execute('SELECT preferred_fiscal_year FROM user_preferences WHERE user_id=?', (user['id'],)).fetchone()
    year = year_row[0] if year_row and year_row[0] else 2026
    for resource in intents:
        params = {'page':1, 'page_size':100, 'order':'asc'}
        if supplier and resource in ('catalog','purchase-orders','invoices','contracts'):
            params['supplier'] = supplier['id']
        if resource == 'purchase-orders':
            if re.search(r'\boverdue\b', text): params['status'] = 'overdue'
            elif re.search(r'\bopen\b', text): params['status'] = 'open'
            if re.search(r'\b(no invoice|without invoice|unmatched)\b', text):
                params['no_invoice'] = True
                if 'status' not in params: params['status'] = 'open'
        if resource == 'invoices' and 'unmatched' in text: params['status'] = 'unmatched'
        result = records.list_records(db, user, resource, params)
        rows = result['items']
        if supplier and resource == 'suppliers':
            rows = [dict(db.execute('SELECT * FROM suppliers WHERE id=?', (supplier['id'],)).fetchone())]
        if supplier and resource == 'spend':
            rows = [dict(r) for r in db.execute('SELECT r.*,s.name AS supplier_name FROM spend_monthly r JOIN suppliers s ON s.id=r.supplier_id WHERE r.supplier_id=? AND r.year=? ORDER BY r.id LIMIT 100', (supplier['id'],year))]
        if supplier and resource == 'requisitions':
            rows = [dict(r) for r in db.execute('SELECT r.*,s.name AS supplier_name,u.display_name AS requester_name FROM requisitions r JOIN suppliers s ON s.id=r.supplier_id JOIN users u ON u.id=r.requester_id WHERE r.supplier_id=? ORDER BY r.id LIMIT 100', (supplier['id'],))]
        if resource == 'knowledge':
            terms = [w for w in re.findall(r'[a-z0-9]+', text) if w not in {'show','me','the','a','an','and','or','policy','policies','knowledge','sop','documents','document','about','what','is','find','for'}]
            if terms:
                ids = {row['id'] for row in db.execute('SELECT id,title,body FROM knowledge_docs') if any(term in (row['title']+' '+row['body']).lower() for term in terms)}
                rows = [r for r in rows if r['id'] in ids]
        columns = records.RESOURCES[resource][3]
        display = [{'id':r['id'], **{key:r.get(key) for key in columns}} for r in rows]
        citations = [{'id':r['id'], 'code':r.get('code') or f"{r['year']}-{r['month']:02d} {r['category']}", 'href':f"/{resource}/{r['id']}" if resource != 'spend' else '/spend'} for r in rows]
        sections.append({'resource':resource, 'table':TABLES[resource], 'source':result['source_label'], 'freshness':result['freshness'], 'columns':columns, 'rows':display, 'citations':citations})
    count = sum(len(s['rows']) for s in sections)
    prose = f'Found {count} matching record(s).' if count else 'No matching records were found.'
    if 'spend' in intents: prose += f' Based on your saved filters, showing FY{year}.'
    return {'text':prose, 'sections':sections, 'choices':[], 'followups':FOLLOWUPS, 'supplier_code':supplier['code'] if supplier and any(s['resource'] == 'suppliers' and s['rows'] for s in sections) else None}


def send(db: sqlite3.Connection, user: sqlite3.Row, body: MessageInput) -> dict:
    """Save a user turn and its answer in the caller's conversation."""
    started = time.perf_counter()
    if body.conversation_id:
        owned(db, user, body.conversation_id)
        conversation_id = body.conversation_id
        last = db.execute("SELECT content FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()
        previous = json.loads(last[0]) if last else None
    else:
        conversation_id, previous = None, None
    answer = perform_action(db, user, body.action) if body.action else answer_question(db, user, body.message, previous)
    if conversation_id is None:
        conversation_id = db.execute('INSERT INTO conversations (user_id,title,created_at) VALUES (?,?,?)', (user['id'],body.message[:80],approvals.now())).lastrowid
    stamp = approvals.now()
    db.execute('INSERT INTO messages (conversation_id,role,content,created_at) VALUES (?,?,?,?)', (conversation_id,'user',body.message,stamp))
    tokens = math.ceil((len(body.message) + len(answer['text'])) / 4)
    answer.update({'tokens':tokens, 'cost_usd':f'{tokens * 0.000002:.4f}', 'latency_ms':round((time.perf_counter()-started)*1000)})
    cursor = db.execute('INSERT INTO messages (conversation_id,role,content,created_at) VALUES (?,?,?,?)', (conversation_id,'assistant',json.dumps(answer),stamp))
    approvals.audit(db, user, 'query', 'conversation', conversation_id, 'Assistant query')
    db.commit()
    return {'conversation_id':conversation_id, 'message_id':cursor.lastrowid, 'answer':answer}


def export_csv(db: sqlite3.Connection, user: sqlite3.Row, conversation_id: int, message_id: int) -> str:
    """Export only the saved, authorized displayed rows as CSV."""
    owned(db, user, conversation_id)
    row = db.execute("SELECT content FROM messages WHERE id=? AND conversation_id=? AND role='assistant'", (message_id,conversation_id)).fetchone()
    if not row: raise HTTPException(404, 'Answer not found.')
    answer = safe_answer(db, user, json.loads(row['content']))
    sections = answer['sections']
    columns = list(dict.fromkeys(key for section in sections for key in section['columns']))
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow((['section'] if len(sections) > 1 else []) + columns)
    for section in sections:
        for item in section['rows']:
            values = [item.get(key, '') for key in columns]
            values = ["'" + str(v) if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in values]
            writer.writerow(([section['table']] if len(sections) > 1 else []) + values)
    return output.getvalue()
