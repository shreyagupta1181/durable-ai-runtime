import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, UniqueConstraint
from app.db.database import Base


class RunEvent(Base):
    __tablename__ = "run_events"

    __table_args__ = (
    UniqueConstraint(
        "run_id",
        "seq",
        name="uq_run_events_run_id_seq",
    ),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("runs.id"),
    nullable=False,)

    seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow
    )