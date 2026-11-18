"""Define the SQLite schema used by the seeded workspace."""
import sqlite3

# Decimal currency is stored as text to avoid SQLite float conversion.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, role TEXT NOT NULL, display_name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','inactive')));
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS user_preferences (user_id INTEGER PRIMARY KEY REFERENCES users(id), preferred_fiscal_year INTEGER);
CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category TEXT NOT NULL, country TEXT NOT NULL, risk TEXT NOT NULL, status TEXT NOT NULL, spend_ytd_usd TEXT NOT NULL, contact_name TEXT NOT NULL, contact_email TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS frequent_suppliers (user_id INTEGER NOT NULL REFERENCES users(id), supplier_id INTEGER NOT NULL REFERENCES suppliers(id), PRIMARY KEY(user_id,supplier_id));
CREATE TABLE IF NOT EXISTS catalog_items (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category TEXT NOT NULL, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), unit_price TEXT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS purchase_orders (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), category TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL, requester_id INTEGER NOT NULL REFERENCES users(id), due_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS po_lines (id INTEGER PRIMARY KEY, po_id INTEGER NOT NULL REFERENCES purchase_orders(id), description TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price TEXT NOT NULL, line_amount TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), po_id INTEGER REFERENCES purchase_orders(id), amount TEXT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL, invoice_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contracts (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), contract_type TEXT NOT NULL, value_usd TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL, manager_id INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS requisitions (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), title TEXT NOT NULL, total_amount_usd TEXT NOT NULL, status TEXT NOT NULL, requester_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requisition_lines (id INTEGER PRIMARY KEY, requisition_id INTEGER NOT NULL REFERENCES requisitions(id), description TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sourcing_events (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, title TEXT NOT NULL, event_type TEXT NOT NULL, status TEXT NOT NULL, end_date TEXT NOT NULL, estimated_value_usd TEXT NOT NULL, winning_supplier_id INTEGER REFERENCES suppliers(id));
CREATE TABLE IF NOT EXISTS sourcing_bids (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES sourcing_events(id), supplier_id INTEGER NOT NULL REFERENCES suppliers(id), amount_usd TEXT NOT NULL, submitted_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS spend_monthly (id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), category TEXT NOT NULL, year INTEGER NOT NULL, month INTEGER NOT NULL, amount_usd TEXT NOT NULL, freshness TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_docs (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, title TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_access (doc_id INTEGER NOT NULL REFERENCES knowledge_docs(id), role TEXT NOT NULL, PRIMARY KEY(doc_id,role));
CREATE TABLE IF NOT EXISTS approvals (id INTEGER PRIMARY KEY, approval_type TEXT NOT NULL, title TEXT NOT NULL, subject_table TEXT NOT NULL, subject_id INTEGER NOT NULL, current_json TEXT NOT NULL, proposed_json TEXT NOT NULL, amount_usd TEXT, risk TEXT NOT NULL, status TEXT NOT NULL, requester_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT);
CREATE TABLE IF NOT EXISTS signatures (id INTEGER PRIMARY KEY, approval_id INTEGER NOT NULL REFERENCES approvals(id), signer_id INTEGER NOT NULL REFERENCES users(id), meaning TEXT NOT NULL, reason TEXT NOT NULL, signed_at TEXT NOT NULL, UNIQUE(approval_id,signer_id));
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, link TEXT);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), role TEXT NOT NULL, action TEXT NOT NULL, record_type TEXT NOT NULL, record_id TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id), role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
"""

def create_tables(db: sqlite3.Connection) -> None:
    """Create missing tables without replacing existing data."""
    db.executescript(SCHEMA)
