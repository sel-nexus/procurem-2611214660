"""Expose administrator-only account management endpoints."""
import sqlite3
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Response
from app.core.database import get_db
from app.routers.auth import require_roles
from app.schemas.users import CreateUser, UpdateUser, UserRecord, UserPage, PasswordResult
from app.services import users

router = APIRouter(prefix='/api/v1/users', tags=['Users'])
Db = Annotated[sqlite3.Connection, Depends(get_db)]
Admin = Annotated[sqlite3.Row, Depends(require_roles('admin'))]

@router.get('', response_model=UserPage)
def list_accounts(db: Db, actor: Admin, search: str = Query('', max_length=100), page: int = Query(1, ge=1, le=2147483647), page_size: int = Query(20, ge=1, le=100), sort: Literal['display_name', 'email', 'role', 'status'] = 'display_name', order: Literal['asc', 'desc'] = 'asc') -> dict:
    """List a searchable page of accounts."""
    return users.list_users(db, search, page, page_size, sort, order)

@router.post('', response_model=PasswordResult, status_code=201)
def create_account(body: CreateUser, response: Response, db: Db, actor: Admin) -> dict:
    """Create an account and return its one-time temporary password."""
    response.headers['Cache-Control'] = 'no-store'
    return users.create_user(db, actor['id'], body)

@router.get('/{user_id}', response_model=UserRecord)
def get_account(user_id: int, db: Db, actor: Admin) -> dict:
    """Read one account without its credential."""
    return users.get_user(db, user_id)

@router.put('/{user_id}', response_model=UserRecord)
def update_account(user_id: int, body: UpdateUser, db: Db, actor: Admin) -> dict:
    """Update an account while protecting the administrator's own access."""
    return users.update_user(db, actor['id'], user_id, body)

@router.post('/{user_id}/reset-password', response_model=PasswordResult)
def reset_account(user_id: int, response: Response, db: Db, actor: Admin) -> dict:
    """Rotate the credential and invalidate all sessions."""
    response.headers['Cache-Control'] = 'no-store'
    return users.reset_password(db, actor['id'], user_id)
