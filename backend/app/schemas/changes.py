"""Validate supplier and sourcing proposals at the API boundary."""
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import re

from app.schemas.approvals import Text


class SupplierEdit(BaseModel):
    """Capture one or more editable supplier fields."""
    model_config = ConfigDict(extra='forbid')
    contact_name: Text | None = None
    contact_email: Text | None = None
    risk: Literal['low', 'medium', 'high'] | None = None
    status: Literal['active', 'inactive'] | None = None

    @field_validator('contact_email')
    @classmethod
    def email_valid(cls, value: str | None) -> str | None:
        """Reject malformed contact addresses."""
        if value is not None and not re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+', value):
            raise ValueError('Enter a valid contact email.')
        return value

    @model_validator(mode='after')
    def nonempty(self):
        """Require at least one non-null field."""
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError('Provide at least one valid field.')
        return self


class SourcingCreate(BaseModel):
    """Capture the details of a proposed sourcing event."""
    model_config = ConfigDict(extra='forbid')
    title: Text
    event_type: Literal['RFQ', 'RFP', 'Auction']
    estimated_value_usd: Decimal = Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)
    end_date: date


class AwardInput(BaseModel):
    """Select the bid to be proposed as the winner."""
    model_config = ConfigDict(extra='forbid')
    bid_id: int = Field(gt=0, strict=True)
