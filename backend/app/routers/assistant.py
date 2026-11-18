"""Expose authenticated assistant conversations and answer exports."""
import sqlite3
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from app.core.database import get_db
from app.routers.auth import get_current_user
from app.schemas.assistant import MessageInput
from app.services import assistant

router = APIRouter(prefix='/api/v1/assistant', tags=['Assistant'])
Db = Annotated[sqlite3.Connection, Depends(get_db)]
User = Annotated[sqlite3.Row, Depends(get_current_user)]


@router.get('/conversations')
def list_conversations(db: Db, user: User, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> dict:
    """List the signed-in user's conversation titles."""
    return assistant.conversations(db, user, page, page_size)


@router.get('/conversations/{conversation_id}')
def get_conversation(conversation_id: int, db: Db, user: User) -> dict:
    """Reopen an owned conversation."""
    return assistant.history(db, user, conversation_id)


@router.post('/messages')
def send_message(body: MessageInput, db: Db, user: User) -> dict:
    """Persist and answer a user message."""
    return assistant.send(db, user, body)


@router.get('/conversations/{conversation_id}/messages/{message_id}/csv')
def download_answer(conversation_id: int, message_id: int, db: Db, user: User) -> Response:
    """Download an owned answer's displayed rows."""
    return Response(assistant.export_csv(db, user, conversation_id, message_id), media_type='text/csv', headers={'Content-Disposition':'attachment; filename="answer.csv"'})
