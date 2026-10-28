import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class ClickEvent(Base):
    __tablename__ = "click_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_click_events_event_id"),
        Index("ix_click_events_link_id_clicked_at", "link_id", "clicked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    link_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("links.id", ondelete="CASCADE"), nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    referrer_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    link: Mapped["Link"] = relationship(back_populates="click_events")
