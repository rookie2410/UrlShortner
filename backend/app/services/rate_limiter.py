import hashlib
import logging
import time
from collections import OrderedDict, deque
from threading import Lock
from typing import Any
from app.core.config import Settings
from app.services.redis_circuit_breaker import RedisCircuitBreaker

logger = logging.getLogger(__name__)


class CreateRateLimiter:
    """Redis-backed rolling-window limiter with a conservative process-local fallback."""

    def __init__(self, redis: Any, settings: Settings, circuit_breaker: RedisCircuitBreaker | None = None):
        self.redis = redis
        self.settings = settings
        self.circuit_breaker = circuit_breaker or RedisCircuitBreaker()
        self._fallback: OrderedDict[str, deque[float]] = OrderedDict()
        self._fallback_max_keys = 10000
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        key_digest = hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()
        redis_key = f"shortlink:ratelimit:create:{key_digest}"
        if not self.circuit_breaker.allow_request():
            return self._fallback_allow(key)
        try:
            pipe = self.redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, self.settings.create_rate_limit_window_seconds)
            count, _ = pipe.execute()
            self.circuit_breaker.record_success()
            return int(count) <= self.settings.create_rate_limit_count
        except Exception as exc:
            self.circuit_breaker.record_failure()
            logger.warning("rate_limit_redis_unavailable", extra={"error_type": type(exc).__name__})
            return self._fallback_allow(key)

    def _fallback_allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.settings.create_rate_limit_window_seconds
        with self._lock:
            times = self._fallback.get(key)
            if times is None:
                if len(self._fallback) >= self._fallback_max_keys:
                    self._fallback.popitem(last=False)
                times = deque()
                self._fallback[key] = times
            self._fallback.move_to_end(key)
            while times and times[0] <= cutoff:
                times.popleft()
            if len(times) >= self.settings.create_rate_limit_count:
                return False
            times.append(now)
            return True
