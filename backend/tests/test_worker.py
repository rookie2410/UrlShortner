import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func
from app.core.config import Settings
from app.models import ClickEvent, Link
from app.schemas.links import ClickEventPayload
from app.worker.worker import ClickWorker


class FakeRedis:
    def __init__(self, pending=None, claimed=None):
        self.acks = []
        self.dead_letters = []
        self.pending = pending or []
        self.claimed = claimed or []
        self.claim_args = []

    def xack(self, stream, group, message_id):
        self.acks.append(message_id)
        return 1

    def xadd(self, stream, fields):
        self.dead_letters.append((stream, fields))
        return "2-0"

    def xpending_range(self, *args, **kwargs):
        min_id = kwargs.get("min")
        if min_id not in (None, "-"):
            return [{"message_id": min_id, "times_delivered": 1}]
        return self.pending

    def xclaim(self, stream, group, consumer, min_idle_time, message_ids):
        self.claim_args.append((min_idle_time, message_ids))
        return self.claimed


def test_worker_persists_then_acknowledges(db_factory):
    with db_factory() as db:
        link = Link(code="AbCdEfG", original_url="https://example.com", is_active=True)
        db.add(link)
        db.commit()
        event = ClickEventPayload(event_id=uuid.uuid4(), link_id=link.id, clicked_at=datetime.now(timezone.utc))

    redis = FakeRedis()
    worker = ClickWorker(redis, db_factory, Settings())
    worker.process_message("1-0", {"payload": event.model_dump_json()})

    with db_factory() as db:
        count = db.scalar(select(func.count(ClickEvent.id)))
    assert count == 1
    assert redis.acks == ["1-0"]


def test_worker_duplicate_event_is_acked_without_duplicate_row(db_factory):
    with db_factory() as db:
        link = Link(code="AbCdEfG", original_url="https://example.com", is_active=True)
        db.add(link)
        db.commit()
        event = ClickEventPayload(event_id=uuid.uuid4(), link_id=link.id, clicked_at=datetime.now(timezone.utc))
    redis = FakeRedis()
    worker = ClickWorker(redis, db_factory, Settings())
    worker.process_message("1-0", {"payload": event.model_dump_json()})
    worker.process_message("2-0", {"payload": event.model_dump_json()})
    with db_factory() as db:
        assert db.scalar(select(func.count(ClickEvent.id))) == 1
    assert redis.acks == ["1-0", "2-0"]


def test_malformed_event_is_dead_lettered_and_acked(db_factory):
    redis = FakeRedis()
    worker = ClickWorker(redis, db_factory, Settings())
    worker.process_message("3-0", {"payload": "not-json"})
    assert redis.dead_letters
    assert redis.acks == ["3-0"]


def test_pending_retry_delay_grows_exponentially(db_factory):
    settings = Settings(worker_pending_idle_ms=1000, worker_max_backoff_seconds=30)
    entry = {"message_id": "9-0", "times_delivered": 2, "time_since_delivered": 1500}
    redis = FakeRedis(pending=[entry])
    worker = ClickWorker(redis, db_factory, settings)
    assert worker.recover_pending() == 0
    assert redis.claim_args == []

    entry["time_since_delivered"] = 2500
    worker.recover_pending()
    assert redis.claim_args[0][0] == 2000
