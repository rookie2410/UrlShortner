import json
import logging
from typing import Any
from app.core.config import Settings
from app.schemas.links import ClickEventPayload
from app.services.redis_circuit_breaker import RedisCircuitBreaker

logger = logging.getLogger(__name__)


class ClickEventQueue:
    def __init__(self, redis: Any, settings: Settings, circuit_breaker: RedisCircuitBreaker | None = None):
        self.redis = redis
        self.settings = settings
        self.circuit_breaker = circuit_breaker or RedisCircuitBreaker()

    def enqueue(self, event: ClickEventPayload) -> bool:
        if not self.circuit_breaker.allow_request():
            logger.error("click_event_enqueue_skipped_circuit_open", extra={"event_id": str(event.event_id), "link_id": str(event.link_id)})
            return False
        try:
            self.redis.xadd(self.settings.click_stream_name, {"payload": event.model_dump_json()})
            self.circuit_breaker.record_success()
            return True
        except Exception as exc:
            self.circuit_breaker.record_failure()
            # Redirects must not depend on analytics persistence, but the loss is visible in logs.
            logger.error(
                "click_event_enqueue_failed",
                extra={"event_id": str(event.event_id), "link_id": str(event.link_id), "error_type": type(exc).__name__},
            )
            return False
