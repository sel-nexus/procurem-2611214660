"""Expose authenticated dashboard and read-only procurement records."""
import sqlite3
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query
from app.core.database import get_db
from app.routers.auth import get_current_user
from app.services import records

router = APIRouter(prefix='/api/v1', tags=['Records'])
Db = Annotated[sqlite3.Connection, Depends(get_db)]
User = Annotated[sqlite3.Row, Depends(get_current_user)]

@router.get('/dashboard')
def dashboard(db: Db, user: User) -> dict:
    """Return current workspace metrics."""
    return records.dashboard(db)

@router.get('/records/{resource}')
def list_records(resource: str, db: Db, user: User, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), sort: str = '', order: Literal['asc','desc'] = 'asc', search: str = Query('', max_length=200), category: str = '', risk: str = '', status: str = '', supplier: str = '', no_invoice: bool = False, year: int | None = Query(None, ge=1900, le=9999), from_month: int | None = Query(None, ge=1, le=12), to_month: int | None = Query(None, ge=1, le=12)) -> dict:
    """List records after validating pagination and filters."""
    return records.list_records(db,user,resource,locals())

@router.get('/records/{resource}/{record_id}')
def detail(resource: str, record_id: int, db: Db, user: User) -> dict:
    """Return one record or a non-disclosing not-found response."""
    return records.detail(db,user,resource,record_id)
