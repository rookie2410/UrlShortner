import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import ClickEvent, Link
from app.services.short_codes import generate_short_code


class ShortCodeExhaustedError(RuntimeError):
    """Short-code generation repeatedly hit unique constraints."""


def create_link(db: Session, original_url: str, expires_at: datetime | None, max_attempts: int = 5) -> Link:
    for _ in range(max_attempts):
        link = Link(code=generate_short_code(), original_url=original_url, expires_at=expires_at, is_active=True)
        db.add(link)
        try:
            db.commit()
            db.refresh(link)
            return link
        except IntegrityError:
            db.rollback()
            # Retry only when the generated code actually collided; propagate unrelated integrity errors.
            if db.scalar(select(Link.id).where(Link.code == link.code)) is not None:
                continue
            raise
    raise ShortCodeExhaustedError("Unable to allocate a unique short code. Please retry.")


def get_link_by_code(db: Session, code: str) -> Link | None:
    return db.scalar(select(Link).where(Link.code == code))


def is_link_unavailable(link: Link, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    # SQLite may return a naive datetime in tests; treat persisted naive values as UTC.
    expiry = link.expires_at
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return (not link.is_active) or (expiry is not None and expiry <= now)


def get_stats(db: Session, link: Link) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    total = db.scalar(select(func.count(ClickEvent.id)).where(ClickEvent.link_id == link.id)) or 0
    recent = db.scalar(
        select(func.count(ClickEvent.id)).where(
            ClickEvent.link_id == link.id,
            ClickEvent.clicked_at >= since,
        )
    ) or 0
    return int(total), int(recent)


def deactivate_link(db: Session, link: Link) -> Link:
    link.is_active = False
    db.commit()
    db.refresh(link)
    return link
