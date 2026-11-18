"""Validate requisition requests and electronic signature input."""
from decimal import Decimal
from html import unescape
import re
from typing import Annotated, Literal
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


def reject_markup(value: str) -> str:
    """Reject HTML-like tags without altering accepted text.

    Decode entities for inspection only, so encoded markup cannot bypass the
    boundary while ordinary ampersands and comparison text are preserved.
    """
    inspected = value
    while True:
        decoded = unescape(inspected)
        if decoded == inspected:
            break
        inspected = decoded
    if re.search(r'<\s*/?\s*[a-z][^>]*>', inspected, re.IGNORECASE) or re.search(r'<\s*/?\s*script\b', inspected, re.IGNORECASE):
        raise ValueError('HTML markup is not allowed.')
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300), AfterValidator(reject_markup)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=1000), AfterValidator(reject_markup)]

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
