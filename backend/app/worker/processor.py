import logging
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import ClickEvent
from app.schemas.links import ClickEventPayload

logger = logging.getLogger(__name__)


def persist_event(db: Session, event: ClickEventPayload) -> bool:
    """Persist once; return False when event_id was already committed."""
    existing = db.scalar(select(ClickEvent.id).where(ClickEvent.event_id == event.event_id))
    if existing is not None:
        # Commit the read-only confirmation before the worker acknowledges the duplicate.
        db.commit()
        return False
    db.add(ClickEvent(
        event_id=event.event_id,
        link_id=event.link_id,
        clicked_at=event.clicked_at,
        referrer_domain=event.referrer_domain,
        user_agent_family=event.user_agent_family,
    ))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        # Handle concurrent duplicate delivery idempotently, but don't hide unrelated constraints.
        existing = db.scalar(select(ClickEvent.id).where(ClickEvent.event_id == event.event_id))
        if existing is not None:
            db.commit()
            return False
        raise
