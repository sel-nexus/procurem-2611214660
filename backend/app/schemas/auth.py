"""Describe the public authentication contract."""
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    """Accept credentials and requested session duration."""
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=72)
    remember_me: bool = False

class UserResponse(BaseModel):
    """Expose identity without credentials."""
    id: int
    email: str
    display_name: str
    role: str

class AdapterStatus(BaseModel):
    """Describe one local adapter's seed state."""
    name: str
    state: str

class HealthResponse(BaseModel):
    """Describe process and local adapter health."""
    status: str
    adapters: list[AdapterStatus]
