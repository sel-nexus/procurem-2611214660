"""Define validated conversation requests and structured approval proposals."""
from typing import Annotated, Literal
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints
from app.schemas.approvals import RequisitionInput, reject_markup
from app.schemas.changes import SupplierEdit, SourcingCreate, AwardInput


class RequisitionAction(BaseModel):
    """Describe a complete requisition submission."""
    model_config = ConfigDict(extra='forbid')
    kind: Literal['requisition']
    details: RequisitionInput


class SupplierAction(BaseModel):
    """Describe an editable supplier and proposed fields."""
    model_config = ConfigDict(extra='forbid')
    kind: Literal['supplier_edit']
    supplier_id: int = Field(gt=0, strict=True)
    details: SupplierEdit


class SourcingAction(BaseModel):
    """Describe a proposed sourcing event."""
    model_config = ConfigDict(extra='forbid')
    kind: Literal['sourcing_create']
    details: SourcingCreate


class AwardAction(BaseModel):
    """Describe a bid selected for a pending award."""
    model_config = ConfigDict(extra='forbid')
    kind: Literal['sourcing_award']
    event_id: int = Field(gt=0, strict=True)
    details: AwardInput


Action = Annotated[RequisitionAction | SupplierAction | SourcingAction | AwardAction, Field(discriminator='kind')]


class MessageInput(BaseModel):
    """Accept a bounded question and an optional complete proposal."""
    model_config = ConfigDict(extra='forbid')
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000), AfterValidator(reject_markup)]
    conversation_id: int | None = Field(default=None, gt=0, strict=True)
    action: Action | None = None
