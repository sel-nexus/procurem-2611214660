"""Expose sign-in, session identity and sign-out endpoints."""
import sqlite3
from typing import Annotated, Callable
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.core.database import get_db
from app.schemas.auth import LoginRequest, UserResponse
from app.services import auth

router = APIRouter(prefix='/api/v1/auth', tags=['Authentication'])
Db = Annotated[sqlite3.Connection, Depends(get_db)]

def get_current_user(request: Request, db: Db) -> sqlite3.Row:
    """Require a valid session for protected routes."""
    return auth.current_user(db, request.cookies.get('procurem_session'))

def require_roles(*roles: str) -> Callable:
    """Build a dependency that rejects roles outside the allowed set."""
    def check(user: Annotated[sqlite3.Row, Depends(get_current_user)]) -> sqlite3.Row:
        """Enforce the route's role boundary."""
        if user['role'] not in roles:
            raise HTTPException(403, 'Permission denied.')
        return user
    return check

def public_user(user: sqlite3.Row) -> UserResponse:
    """Project the public identity fields."""
    return UserResponse(id=user['id'], email=user['email'], display_name=user['display_name'], role=user['role'])

@router.post('/login', response_model=UserResponse, summary='Sign in')
def login(body: LoginRequest, request: Request, response: Response, db: Db) -> UserResponse:
    """Create a persistent session from valid credentials."""
    user, token, seconds = auth.login(db, body.email, body.password, body.remember_me)
    response.set_cookie('procurem_session',token,max_age=seconds,httponly=True,secure=request.app.state.settings.cookie_secure,samesite='lax',path='/')
    return public_user(user)

@router.get('/me', response_model=UserResponse, summary='Get current identity')
def me(user: Annotated[sqlite3.Row, Depends(get_current_user)]) -> UserResponse:
    """Return the authenticated identity."""
    return public_user(user)

@router.post('/logout', status_code=204, summary='Sign out')
def logout(request: Request, db: Db, user: Annotated[sqlite3.Row, Depends(get_current_user)]) -> Response:
    """Revoke the current session and clear its cookie."""
    auth.logout(db, request.cookies['procurem_session'])
    response = Response(status_code=204)
    response.delete_cookie('procurem_session',path='/',secure=request.app.state.settings.cookie_secure,httponly=True,samesite='lax')
    return response
