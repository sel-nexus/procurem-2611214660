"""Validate requisition requests and electronic signature input."""
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=1000)]

class LineInput(BaseModel):
    """Describe a positive, precisely priced requisition line."""
    model_config = ConfigDict(extra='forbid')
    description: Text
    quantity: int = Field(gt=0, le=1000000, strict=True)
    unit_price: Decimal = Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)

class RequisitionInput(BaseModel):
    """Capture a complete requisition draft."""
    model_config = ConfigDict(extra='forbid')
    supplier_id: int = Field(gt=0, strict=True)
    title: Text
    reason: Text
    lines: list[LineInput] = Field(min_length=1, max_length=100)

class SignatureInput(BaseModel):
    """Capture a decision without persisting the supplied password."""
    model_config = ConfigDict(extra='forbid')
    meaning: Literal['Approved', 'Rejected']
    reason: Reason
    password: str = Field(min_length=1, max_length=72)
