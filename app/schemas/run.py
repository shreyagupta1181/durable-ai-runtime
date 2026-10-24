
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RunResponse(BaseModel):
    id: UUID
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunStatusUpdate(BaseModel):
    status: str
