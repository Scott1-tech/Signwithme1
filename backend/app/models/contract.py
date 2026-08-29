import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, updated_at_col, uuid_pk

# uploaded -> parsing -> analyzed -> reviewing -> signing -> completed (or failed)
CONTRACT_STATUSES = (
    "uploaded",
    "parsing",
    "analyzed",
    "reviewing",
    "signing",
    "completed",
    "failed",
)
REVIEW_STATUSES = ("pending", "approved", "rejected")


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        Index("idx_contracts_template", "template_id"),
        Index("idx_contracts_status", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id", ondelete="RESTRICT"), nullable=False
    )

    contractor_name: Mapped[str | None] = mapped_column(String(255))
    contractor_email: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Final signed artifact, populated by the finalize step.
    final_file_path: Mapped[str | None] = mapped_column(String(500))
    final_file_hash: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(50), default="uploaded", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Denormalised read cache of contract_fields; contract_fields stays authoritative.
    extracted_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    comparison_result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    review_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    template: Mapped["Template"] = relationship(back_populates="contracts")  # noqa: F821
    fields: Mapped[list["ContractField"]] = relationship(  # noqa: F821
        back_populates="contract", cascade="all, delete-orphan"
    )
    signatures: Mapped[list["Signature"]] = relationship(  # noqa: F821
        back_populates="contract", cascade="all, delete-orphan"
    )
