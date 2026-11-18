"""Expose requisition and approval operations to authenticated users."""
import sqlite3
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Response
from app.core.database import get_db
from app.routers.auth import get_current_user, require_roles
from app.schemas.approvals import RequisitionInput, SignatureInput
from app.services import approvals

router = APIRouter(prefix='/api/v1', tags=['Approvals'])
Db = Annotated[sqlite3.Connection, Depends(get_db)]
User = Annotated[sqlite3.Row, Depends(get_current_user)]
Reviewer = Annotated[sqlite3.Row, Depends(require_roles('procurement_manager', 'compliance'))]

@router.post('/requisitions', status_code=201)
def create_requisition(body: RequisitionInput, db: Db, user: User) -> dict:
    """Create an analyst's requisition draft."""
    return approvals.create_draft(db,user,body)

@router.post('/requisitions/{record_id}/submit')
def submit_requisition(record_id: int, db: Db, user: User) -> dict:
    """Submit an existing owned draft."""
    return approvals.submit(db,user,record_id)

@router.get('/approvals')
def inbox(db: Db, user: User, page: int = Query(1, ge=1, le=2147483647), page_size: int = Query(20, ge=1, le=100), sort: str = 'id', order: Literal['asc','desc'] = 'asc') -> dict:
    """Return the shared approval inbox."""
    return approvals.list_approvals(db,page,page_size,sort,order)

@router.get('/approvals/pending-count')
def pending_count(db: Db, user: Reviewer, response: Response) -> dict:
    """Count approvals the current reviewer is eligible to sign."""
    response.headers['Cache-Control'] = 'no-store'
    return {'count': approvals.pending_count(db, user)}


@router.get('/approvals/{approval_id}')
def approval_detail(approval_id: int, db: Db, user: User) -> dict:
    """Return an approval and its signature history."""
    return approvals.detail(db,approval_id,user)

@router.post('/approvals/{approval_id}/sign')
def signature(approval_id: int, body: SignatureInput, db: Db, user: User) -> dict:
    """Record a password-confirmed decision if it is the user's turn."""
    return approvals.sign(db,user,approval_id,body)
