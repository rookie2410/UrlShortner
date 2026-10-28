import threading
import time


class RedisCircuitBreaker:
    """Small process-local breaker that prevents repeated Redis outages adding latency."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout_seconds: float = 10.0):
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout_seconds = max(0.1, recovery_timeout_seconds)
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._opened_at is None:
                return True
            if now - self._opened_at < self.recovery_timeout_seconds:
                return False
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._failures += 1
            self._probe_in_flight = False
            if self._opened_at is not None or self._failures >= self.failure_threshold:
                self._opened_at = now

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None and time.monotonic() - self._opened_at < self.recovery_timeout_seconds
