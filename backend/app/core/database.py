"""Manage persistent SQLite connections."""
import sqlite3
from pathlib import Path
from collections.abc import Iterator
from fastapi import Request

def connect(path: str) -> sqlite3.Connection:
    """Open a connection and enforce foreign keys."""
    if path == ':memory:':
        raise ValueError('A file-backed database is required')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """Provide a request-scoped connection."""
    db = connect(request.app.state.settings.database_path)
    try:
        yield db
    finally:
        db.close()
