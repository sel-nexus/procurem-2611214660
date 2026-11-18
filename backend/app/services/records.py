"""Read procurement records using fixed, parameterized SQLite queries."""
import sqlite3
from decimal import Decimal
from fastapi import HTTPException

# All SQL fragments below are application-owned, never provided by callers.
RESOURCES = {
    'suppliers': ("suppliers r", "r.*", 'JAGGAER', ['code','name','category','country','risk','status','spend_ytd_usd'], ['name','code']),
    'catalog': ("catalog_items r JOIN suppliers s ON s.id=r.supplier_id", "r.*, s.name AS supplier_name", 'Catalog', ['code','name','category','supplier_name','unit_price','currency','status'], ['name','code']),
    'purchase-orders': ("purchase_orders r JOIN suppliers s ON s.id=r.supplier_id JOIN users u ON u.id=r.requester_id", "r.*, s.name AS supplier_name, u.display_name AS requester_name, EXISTS(SELECT 1 FROM invoices i WHERE i.po_id=r.id) AS has_invoice", 'Oracle', ['code','supplier_name','category','amount','currency','status','requester_name','due_date','has_invoice'], ['code']),
    'invoices': ("invoices r JOIN suppliers s ON s.id=r.supplier_id LEFT JOIN purchase_orders p ON p.id=r.po_id", "r.*, s.name AS supplier_name, p.code AS po_code", 'Oracle', ['code','supplier_name','po_code','amount','currency','status','invoice_date'], ['code']),
    'contracts': ("contracts r JOIN suppliers s ON s.id=r.supplier_id JOIN users u ON u.id=r.manager_id", "r.*, s.name AS supplier_name, u.display_name AS manager_name", 'Oracle', ['code','supplier_name','contract_type','value_usd','start_date','end_date','status'], ['code']),
    'requisitions': ("requisitions r JOIN suppliers s ON s.id=r.supplier_id JOIN users u ON u.id=r.requester_id", "r.*, s.name AS supplier_name, u.display_name AS requester_name", 'Oracle', ['code','title','supplier_name','total_amount_usd','status','requester_name','created_at'], ['code','title']),
    'sourcing': ("sourcing_events r", "r.*, (SELECT count(*) FROM sourcing_bids b WHERE b.event_id=r.id) AS bid_count", 'JAGGAER', ['code','title','event_type','status','end_date','bid_count','estimated_value_usd'], ['code','title']),
    'spend': ("spend_monthly r JOIN suppliers s ON s.id=r.supplier_id", "r.*, s.name AS supplier_name", 'Spend', ['category','year','month','amount_usd','supplier_name'], []),
    'knowledge': ("knowledge_docs r", "r.id,r.code,r.title,r.version,r.updated_at", 'Knowledge', ['code','title','version','updated_at'], ['title','body']),
}
MONEY = {'spend_ytd_usd','unit_price','amount','value_usd','total_amount_usd','estimated_value_usd','amount_usd'}
FILTERS = {
    'suppliers': {'category':'r.category','risk':'r.risk','status':'r.status'},
    'catalog': {'category':'r.category','supplier':'r.supplier_id'},
    'purchase-orders': {'status':'r.status','supplier':'r.supplier_id'},
    'invoices': {'status':'r.status','supplier':'r.supplier_id'},
    'contracts': {'status':'r.status','supplier':'r.supplier_id'},
    'spend': {'category':'r.category'},
}

def config(resource: str) -> tuple:
    """Resolve a permitted resource or hide unknown tables."""
    if resource not in RESOURCES:
        raise HTTPException(404, 'Record not found.')
    return RESOURCES[resource]

def list_records(db: sqlite3.Connection, user: sqlite3.Row, resource: str, params: dict) -> dict:
    """Return a bounded, authorized page with stable sorting."""
    table, fields, source, columns, searchable = config(resource)
    sort = params.get('sort') or columns[0]
    if sort not in columns:
        raise HTTPException(422, 'Invalid sort field.')
    clauses, values = [], []
    if resource == 'knowledge':
        clauses.append('EXISTS (SELECT 1 FROM knowledge_access ka WHERE ka.doc_id=r.id AND ka.role=?)')
        values.append(user['role'])
    query = params.get('search', '').strip()
    if query and searchable:
        clauses.append('(' + ' OR '.join(f'LOWER(r.{field}) LIKE ? ESCAPE "\\"' for field in searchable) + ')')
        escaped = query.lower().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        values.extend([f'%{escaped}%'] * len(searchable))
    for key, expression in FILTERS.get(resource, {}).items():
        if params.get(key):
            clauses.append(f'{expression}=?')
            values.append(params[key])
    if resource == 'purchase-orders' and params.get('no_invoice'):
        clauses.append('NOT EXISTS (SELECT 1 FROM invoices i WHERE i.po_id=r.id)')
    if resource == 'spend':
        year = db.execute('SELECT preferred_fiscal_year FROM user_preferences WHERE user_id=?', (user['id'],)).fetchone()
        selected_year = params.get('year') or (year[0] if year and year[0] else 2026)
        clauses.append('r.year=?')
        values.append(selected_year)
        for key, op in [('from_month','>='), ('to_month','<=')]:
            if params.get(key) is not None:
                clauses.append(f'r.month {op} ?')
                values.append(params[key])
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    total = db.execute(f'SELECT count(*) FROM {table}{where}', values).fetchone()[0]
    order = params['order'].upper()
    sort_sql = f'CAST(r.{sort} AS NUMERIC)' if sort in MONEY else f'"{sort}" COLLATE NOCASE'
    rows = db.execute(f'SELECT {fields} FROM {table}{where} ORDER BY {sort_sql} {order}, r.id ASC LIMIT ? OFFSET ?', [*values, params['page_size'], (params['page']-1)*params['page_size']]).fetchall()
    result = {'items':[dict(row) for row in rows], 'total':total, 'page':params['page'], 'page_size':params['page_size'], 'source_label':f'Mock · {source}', 'freshness':'Analytical' if resource == 'spend' else 'Real-time'}
    if resource == 'spend':
        totals = {}
        for row in db.execute(f'SELECT r.year,r.month,r.amount_usd FROM {table}{where}', values):
            month = f"{row['year']}-{row['month']:02d}"
            totals[month] = totals.get(month, Decimal('0')) + Decimal(row['amount_usd'])
        result['chart'] = [{'month':month,'amount_usd':str(value)} for month,value in sorted(totals.items())]
    return result

def detail(db: sqlite3.Connection, user: sqlite3.Row, resource: str, record_id: int) -> dict:
    """Return one authorized record and its relevant related rows."""
    table, fields, source, _, _ = config(resource)
    if resource == 'knowledge':
        fields = 'r.id,r.code,r.title,r.body,r.version,r.updated_at'
        row = db.execute(f'SELECT {fields} FROM {table} WHERE r.id=? AND EXISTS (SELECT 1 FROM knowledge_access ka WHERE ka.doc_id=r.id AND ka.role=?)', (record_id,user['role'])).fetchone()
    else:
        row = db.execute(f'SELECT {fields} FROM {table} WHERE r.id=?', (record_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Record not found.')
    relations = {}
    queries = {
        'suppliers': {'purchase-orders':'SELECT id,code FROM purchase_orders WHERE supplier_id=?', 'contracts':'SELECT id,code FROM contracts WHERE supplier_id=?', 'catalog':'SELECT id,code,name FROM catalog_items WHERE supplier_id=?'},
        'purchase-orders': {'lines':'SELECT description,quantity,unit_price,line_amount FROM po_lines WHERE po_id=?', 'invoices':'SELECT id,code FROM invoices WHERE po_id=?'},
        'requisitions': {'lines':'SELECT description,quantity,unit_price FROM requisition_lines WHERE requisition_id=?'},
        'sourcing': {'bids':'SELECT b.id,b.supplier_id,s.name AS supplier_name,b.amount_usd,b.submitted_date FROM sourcing_bids b JOIN suppliers s ON s.id=b.supplier_id WHERE b.event_id=?'},
    }
    for name, sql in queries.get(resource, {}).items():
        relations[name] = [dict(item) for item in db.execute(sql, (record_id,))]
    return {'item':dict(row), 'relations':relations, 'source_label':f'Mock · {source}', 'freshness':'Analytical' if resource == 'spend' else 'Real-time'}

def dashboard(db: sqlite3.Connection) -> dict:
    """Calculate real-time counts and exact USD sums from stored rows."""
    supplier_count = db.execute('SELECT count(*) FROM suppliers').fetchone()[0]
    orders = db.execute("SELECT amount,currency FROM purchase_orders WHERE status='open'").fetchall()
    no_invoice = db.execute("SELECT count(*) FROM purchase_orders p WHERE p.status='open' AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.po_id=p.id)").fetchone()[0]
    pending = db.execute("SELECT count(*) FROM approvals WHERE status='pending'").fetchone()[0]
    latest = db.execute('SELECT year,month FROM spend_monthly ORDER BY year DESC,month DESC LIMIT 1').fetchone()
    spend = []
    if latest:
        rows = db.execute('SELECT category,amount_usd FROM spend_monthly WHERE year=? AND month=?', tuple(latest)).fetchall()
        amounts = {}
        for row in rows:
            amounts[row['category']] = amounts.get(row['category'], Decimal('0')) + Decimal(row['amount_usd'])
        spend = [{'category':key, 'amount_usd':str(value)} for key,value in amounts.items()]
    required = ['suppliers','catalog_items','purchase_orders','invoices','contracts','requisitions','sourcing_events','spend_monthly','knowledge_docs']
    return {'supplier_count':supplier_count, 'open_order_count':len(orders), 'no_invoice_count':no_invoice, 'open_order_usd':str(sum((Decimal(row['amount']) for row in orders if row['currency']=='USD'), Decimal('0'))), 'pending_approval_count':pending, 'spend':spend, 'latest_month':f'{latest[0]}-{latest[1]:02d}' if latest else None, 'demo_data_loaded':all(db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() for table in required)}
