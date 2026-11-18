"""Validate account administration requests and responses."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal['analyst', 'category_manager', 'procurement_manager', 'sourcing_specialist', 'finance_analyst', 'compliance', 'admin']
Status = Literal['active', 'inactive']

class CreateUser(BaseModel):
    """Accept a new account without accepting credentials from the client."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    display_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    role: Role

    @field_validator('email')
    @classmethod
    def valid_email(cls, value: str) -> str:
        """Reject malformed addresses and normalize their case."""
        if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", value) or len(value.split('@')[0]) > 64:
            raise ValueError('Enter a valid email address.')
        return value.lower()

class UpdateUser(BaseModel):
    """Accept editable account fields only."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    display_name: str = Field(min_length=1, max_length=100)
    role: Role
    status: Status

class UserRecord(BaseModel):
    """Expose account data without its password hash."""
    id: int
    display_name: str
    email: str
    role: Role
    status: Status

class UserPage(BaseModel):
    """Describe a bounded account listing."""
    items: list[UserRecord]
    total: int
    page: int
    page_size: int

class PasswordResult(BaseModel):
    """Return the freshly generated password only in the mutation response."""
    user: UserRecord
    temporary_password: str
