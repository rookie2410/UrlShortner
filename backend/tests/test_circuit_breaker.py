from app.cache.redirect_cache import RedirectCache
from app.core.config import Settings
from app.queue.click_queue import ClickEventQueue
from app.schemas.links import ClickEventPayload
from app.services.redis_circuit_breaker import RedisCircuitBreaker
from datetime import datetime, timezone
import uuid


class FlakyRedis:
    def __init__(self):
        self.fail = True
        self.get_calls = 0
        self.xadd_calls = 0
        self.values = {}

    def get(self, key):
        self.get_calls += 1
        if self.fail: raise TimeoutError("offline")
        return self.values.get(key)

    def xadd(self, stream, fields):
        self.xadd_calls += 1
        if self.fail: raise TimeoutError("offline")
        return "1-0"


def test_redirect_cache_opens_circuit_after_repeated_redis_failures():
    redis = FlakyRedis()
    breaker = RedisCircuitBreaker(failure_threshold=2, recovery_timeout_seconds=60)
    cache = RedirectCache(redis, Settings(), breaker)
    assert cache.get("AbCdEfG") is None
    assert cache.get("AbCdEfG") is None
    assert cache.get("AbCdEfG") is None
    assert redis.get_calls == 2


def test_queue_circuit_stops_repeated_enqueue_timeouts():
    redis = FlakyRedis()
    breaker = RedisCircuitBreaker(failure_threshold=2, recovery_timeout_seconds=60)
    queue = ClickEventQueue(redis, Settings(), breaker)
    event = ClickEventPayload(event_id=uuid.uuid4(), link_id=uuid.uuid4(), clicked_at=datetime.now(timezone.utc))
    assert queue.enqueue(event) is False
    assert queue.enqueue(event) is False
    assert queue.enqueue(event) is False
    assert redis.xadd_calls == 2
