"""Expose private settings, notifications, audit and role directory."""
import sqlite3
from datetime import date
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.routers.auth import get_current_user, require_roles
from app.services import workspace

router = APIRouter(prefix='/api/v1', tags=['Workspace'])
Db = Annotated[sqlite3.Connection, Depends(get_db)]
User = Annotated[sqlite3.Row, Depends(get_current_user)]
Auditor = Annotated[sqlite3.Row, Depends(require_roles('procurement_manager', 'compliance', 'admin'))]
DirectoryUser = Annotated[sqlite3.Row, Depends(require_roles('compliance', 'admin'))]


class YearInput(BaseModel):
    """Accept an optional preferred fiscal year."""
    preferred_fiscal_year: int | None = Field(ge=1900, le=9999)


@router.get('/settings')
def get_settings(db: Db, user: User) -> dict:
    """Read the signed-in user's workspace settings."""
    return workspace.settings(db, user)


@router.put('/settings/fiscal-year', status_code=204)
def put_year(body: YearInput, db: Db, user: User) -> Response:
    """Save the signed-in user's fiscal year."""
    workspace.save_year(db, user['id'], body.preferred_fiscal_year)
    return Response(status_code=204)


@router.delete('/settings/frequent-suppliers/{supplier_id}', status_code=204)
def delete_supplier(supplier_id: int, db: Db, user: User) -> Response:
    """Remove a saved association without removing its supplier."""
    workspace.remove_supplier(db, user['id'], supplier_id)
    return Response(status_code=204)


@router.delete('/settings/conversations', status_code=204)
def delete_history(db: Db, user: User) -> Response:
    """Clear only the signed-in user's conversation history."""
    workspace.clear_history(db, user['id'])
    return Response(status_code=204)


@router.get('/notifications')
def get_notifications(db: Db, user: User, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> dict:
    """List the caller's notifications."""
    return workspace.notifications(db, user['id'], page, page_size)


@router.get('/notifications/unread-count')
def count_notifications(db: Db, user: User) -> dict:
    """Return the caller's unread count."""
    return {'count': workspace.unread_count(db, user['id'])}


@router.post('/notifications/{notification_id}/read')
def read_notification(notification_id: int, db: Db, user: User) -> dict:
    """Mark an owned notification as read."""
    return workspace.mark_read(db, user['id'], notification_id)


def audit_params(user_id: int | None, action: str, from_date: date | None, to_date: date | None) -> tuple:
    """Validate the inclusive audit date range."""
    if from_date and to_date and from_date > to_date:
        raise HTTPException(422, 'From date must not be after to date.')
    return (user_id, action, from_date.isoformat() if from_date else None, to_date.isoformat() if to_date else None)


@router.get('/audit')
def get_audit(db: Db, user: Auditor, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user_id: int | None = Query(None, ge=1), action: str = Query('', max_length=100), from_date: date | None = None, to_date: date | None = None, sort: str = 'created_at', order: Literal['asc', 'desc'] = 'desc') -> dict:
    """Return a filtered page of immutable audit rows."""
    return workspace.audit(db, *audit_params(user_id, action, from_date, to_date), page, page_size, sort, order)


@router.get('/audit/csv')
def export_audit(db: Db, user: Auditor, user_id: int | None = Query(None, ge=1), action: str = Query('', max_length=100), from_date: date | None = None, to_date: date | None = None, sort: str = 'created_at', order: Literal['asc', 'desc'] = 'desc') -> Response:
    """Export all rows matching the current filters, safely quoted."""
    rows = workspace.audit(db, *audit_params(user_id, action, from_date, to_date), None, 20, sort, order)['items']
    return Response(workspace.audit_csv(rows), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="audit.csv"', 'Cache-Control': 'no-store'})


@router.get('/roles')
def role_directory(db: Db, user: DirectoryUser, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> dict:
    """List users and their roles for authorized reviewers."""
    return workspace.directory(db, page, page_size)
