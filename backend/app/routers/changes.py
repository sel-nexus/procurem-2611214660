"""Expose role-gated supplier and sourcing proposals."""
import sqlite3
from typing import Annotated
from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.routers.auth import require_roles
from app.schemas.changes import SupplierEdit, SourcingCreate, AwardInput
from app.services import changes

router = APIRouter(prefix='/api/v1', tags=['Changes'])
Db = Annotated[sqlite3.Connection, Depends(get_db)]
User = Annotated[sqlite3.Row, Depends(require_roles('category_manager','sourcing_specialist'))]

@router.post('/suppliers/{record_id}/proposals', status_code=201)
def propose_supplier(record_id: int, body: SupplierEdit, db: Db, user: User) -> dict:
    """Submit editable supplier fields for approval."""
    return changes.supplier_edit(db,user,record_id,body)

@router.post('/sourcing', status_code=201)
def create_sourcing(body: SourcingCreate, db: Db, user: User) -> dict:
    """Submit a new event for approval."""
    return changes.sourcing_create(db,user,body)

@router.post('/sourcing/{record_id}/awards', status_code=201)
def request_award(record_id: int, body: AwardInput, db: Db, user: User) -> dict:
    """Submit a bid selection for approval."""
    return changes.award(db,user,record_id,body)
