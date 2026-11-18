from uuid import UUID

from sqlalchemy import CheckConstraint, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.persistence import Base


class AIIndexRecord(Base):
    """Gate retrieval until both external indexes contain an immutable document."""

    __tablename__ = "ai_index_records"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'ready', 'failed')", name="status"),
        CheckConstraint("chunk_count >= 0", name="chunk_count"),
    )

    namespace: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    collection: Mapped[str] = mapped_column(String(128), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_profile: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16))
    chunk_count: Mapped[int]
    error_code: Mapped[str | None] = mapped_column(String(64))
