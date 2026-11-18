"""Seed a coherent local procurement demo once, atomically."""
import json
import sqlite3
from app.core.security import hash_password

ROLES = ['analyst','category_manager','procurement_manager','sourcing_specialist','finance_analyst','compliance','admin']
CATEGORIES = ['Lab Reagents','Lab Equipment','Packaging','IT','Facilities','Professional Services']
NOW = '2026-07-07T00:00:00+00:00'


def seed_database(db: sqlite3.Connection) -> bool:
    """Insert the demo dataset only if no users exist.

    Returns:
        Whether this call inserted the seed.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            db.rollback()
            return False
        accounts = [('analyst@procurem.demo','Priya Shah'),('category.mgr@procurem.demo','Lena Berg'),('proc.manager@procurem.demo','David Okonkwo'),('sourcing@procurem.demo','Amir Rahman'),('finance@procurem.demo','Sofia Alvarez'),('compliance@procurem.demo','Grace Adeyemi'),('admin@procurem.demo','Helen Cho')]
        for i, (email, name) in enumerate(accounts, 1):
            password_hash = hash_password('Admin@5678' if i == 7 else 'Demo@1234')
            db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)', (i,email,password_hash,ROLES[i-1],name,'active'))
            db.execute('INSERT INTO user_preferences VALUES (?,?)', (i,2026 if i == 1 else None))
        names = ['Thermo Fisher','Merck','Avantor','VWR International','Eppendorf','Corning','Sartorius','Agilent','Bio-Rad','Fisher Scientific','Labcorp','Sigma Supply']
        for i, name in enumerate(names, 1):
            db.execute('INSERT INTO suppliers VALUES (?,?,?,?,?,?,?,?,?,?)', (i,f'SUP-{4000+i}',name,CATEGORIES[(i-1)%6],'United States','high' if i == 3 else 'medium' if i == 4 else 'low','inactive' if i == 12 else 'active',f'{i*12000}.00',f'{name} contact',f'contact{i}@supplier.demo'))
        db.execute('INSERT INTO frequent_suppliers VALUES (1,1)')
        for i in range(1,16):
            db.execute('INSERT INTO catalog_items VALUES (?,?,?,?,?,?,?,?)',(i,f'CAT-{7000+i}',f'Laboratory item {i}',CATEGORIES[(i-1)%6],(i-1)%12+1,f'{i*25}.00','USD','inactive' if i == 15 else 'active'))
        for i in range(1,25):
            status = 'open' if i <= 8 else 'overdue' if i <= 12 else 'pending_approval' if i == 13 else 'closed'
            currency = 'EUR' if i == 22 else 'GBP' if i == 23 else 'USD'
            db.execute('INSERT INTO purchase_orders VALUES (?,?,?,?,?,?,?,?,?)',(i,f'PO-{1000+i}',(i-1)%12+1,CATEGORIES[(i-1)%6],'2000.00',currency,status,1,'2026-06-01' if status == 'overdue' else '2026-09-01'))
            for j in range(2):
                db.execute('INSERT INTO po_lines (po_id,description,quantity,unit_price,line_amount) VALUES (?,?,?,?,?)',(i,f'Supply line {j+1}',1,'1000.00','1000.00'))
        for i in range(1,17):
            po = None if i <= 4 else i-4+8
            supplier = (po-1)%12+1 if po else (i-1)%12+1
            db.execute('INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?)',(i,f'INV-{6000+i}',supplier,po,'2000.00','USD','unmatched' if po is None else 'matched' if i%2 else 'paid','2026-06-15'))
        for i in range(1,11):
            status = 'expiring_soon' if i <= 2 else 'expired' if i == 3 else 'active'
            end = '2026-08-01' if i <= 2 else '2026-05-01' if i == 3 else '2027-12-31'
            db.execute('INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?)',(i,f'CON-{5000+i}',i,['MSA','SOW','NDA','Framework'][(i-1)%4],'25000.00','2025-01-01',end,status,2))
        for i in range(1,9):
            status = ['pending_approval','draft','approved','rejected'][(i-1)%4]
            db.execute('INSERT INTO requisitions VALUES (?,?,?,?,?,?,?,?,?)',(i,f'REQ-{2000+i}',i,f'Laboratory supplies {i}','4000.00',status,1,'Restock laboratory supplies',NOW))
            for j in range(2):
                db.execute('INSERT INTO requisition_lines (requisition_id,description,quantity,unit_price) VALUES (?,?,?,?)',(i,f'Supply line {j+1}',1,'2000.00'))
        for i in range(1,7):
            status = ['active','active','awarded','closed','active','closed'][i-1]
            db.execute('INSERT INTO sourcing_events VALUES (?,?,?,?,?,?,?,?)',(i,f'SE-{3000+i}',f'Sourcing event {i}',['RFQ','RFP','Auction'][(i-1)%3],status,'2026-08-31','15000.00' if i == 1 else '5000.00',3 if status == 'awarded' else None))
            for j in range(2):
                db.execute('INSERT INTO sourcing_bids (event_id,supplier_id,amount_usd,submitted_date) VALUES (?,?,?,?)',(i,(i+j-1)%12+1,'15000.00' if i == 1 else '5000.00','2026-06-20'))
        for month in range(1,7):
            for i, category in enumerate(CATEGORIES):
                db.execute('INSERT INTO spend_monthly (supplier_id,category,year,month,amount_usd,freshness) VALUES (?,?,?,?,?,?)',(i+1,category,2026,month,f'{(i+1)*1000+month*100}.00','Analytical'))
        docs = [('Procurement Policy',ROLES),('Supplier Code of Conduct',ROLES),('PO Creation SOP',['analyst','procurement_manager','admin']),('Sourcing Event Launch SOP',['category_manager','sourcing_specialist','procurement_manager']),('Spend Approval Matrix',['procurement_manager','finance_analyst','compliance','admin']),('Vendor Onboarding SOP',['category_manager','sourcing_specialist'])]
        for i, (title, roles) in enumerate(docs,1):
            db.execute('INSERT INTO knowledge_docs VALUES (?,?,?,?,?,?)',(i,f'DOC-{8000+i}',title,f'{title}: Follow the documented review and approval process before proceeding.','1.0','2026-06-01'))
            db.executemany('INSERT INTO knowledge_access VALUES (?,?)',[(i,role) for role in roles])
        approvals = [('requisition','Laboratory supplies 1','requisitions',1,{}, {'status':'approved'},'4000.00','low','pending',1,'Restock supplies',None),('sourcing_award','Sourcing event 1 award','sourcing_events',1,{'status':'active'},{'status':'awarded','winning_supplier_id':1},'15000.00','high','pending',4,'Select the leading bid',None),('sourcing_award','Sourcing event 3 award','sourcing_events',3,{'status':'active'},{'status':'awarded','winning_supplier_id':3},'5000.00','low','approved',4,'Select the leading bid',NOW)]
        for i, (kind,title,table,subject,current,proposed,amount,risk,status,requester,reason,decided) in enumerate(approvals,1):
            db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(i,kind,title,table,subject,json.dumps(current),json.dumps(proposed),amount,risk,status,requester,reason,NOW,decided))
        db.execute('INSERT INTO signatures VALUES (1,3,3,?,?,?)',('Approved','Award meets requirements',NOW))
        for i, title in enumerate(['Requisition awaiting approval','Award awaiting approval'],1):
            db.execute('INSERT INTO notifications VALUES (?,?,?,?,?,?,?)',(i,3,title,'A request is waiting for your review.',NOW,0,f'/approvals/{i}'))
        db.execute('INSERT INTO audit_log VALUES (1,NULL,?,?,?,?,?,?)',('system','seed','workspace','seed','Demo data loaded',NOW))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
