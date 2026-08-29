import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class AuditLog(Base):
    """Append-only legal record. actor_id is deliberately NOT a foreign key so
    log rows survive user deletion."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_contract", "contract_id"),
        Index("idx_audit_timestamp", "timestamp"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL")
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL")
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    actor_role: Mapped[str | None] = mapped_column(String(50))

    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
