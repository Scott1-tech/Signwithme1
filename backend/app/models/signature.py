import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid_pk
from app.models.types import INETType, JSONType, UUIDType

SIGNER_ROLES = ("contractor", "company_rep")


class Signature(Base):
    __tablename__ = "signatures"

    id: Mapped[uuid.UUID] = uuid_pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )

    signer_name: Mapped[str | None] = mapped_column(String(255))
    signer_email: Mapped[str | None] = mapped_column(String(255))
    signer_role: Mapped[str] = mapped_column(String(50), default="contractor", nullable=False)

    signature_image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    signature_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Canonical bbox: PDF points, top-left origin.
    bbox: Mapped[dict] = mapped_column(JSONType, nullable=False)
    field_id: Mapped[str | None] = mapped_column(String(100))

    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(INETType)
    user_agent: Mapped[str | None] = mapped_column(Text)

    contract: Mapped["Contract"] = relationship(back_populates="signatures")  # noqa: F821
