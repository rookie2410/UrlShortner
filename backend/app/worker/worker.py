import json
import logging
import time
import uuid
from threading import Event
from typing import Any

try:
    from redis.exceptions import ResponseError
except ImportError:  # redis is installed by the backend project dependencies
    class ResponseError(Exception):
        pass
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import Settings
from app.schemas.links import ClickEventPayload
from app.worker.processor import persist_event

logger = logging.getLogger(__name__)


class ClickWorker:
    def __init__(self, redis: Any, session_factory: sessionmaker[Session], settings: Settings):
        self.redis = redis
        self.session_factory = session_factory
        self.settings = settings
        self.consumer = f"{settings.worker_consumer_name}-{uuid.uuid4().hex[:8]}"

    def ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(self.settings.click_stream_name, self.settings.click_consumer_group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    @staticmethod
    def _payload(fields: dict) -> ClickEventPayload:
        value = fields.get("payload")
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if not isinstance(value, str):
            raise ValueError("Missing click event payload")
        return ClickEventPayload.model_validate_json(value)

    def _ack(self, message_id) -> None:
        self.redis.xack(self.settings.click_stream_name, self.settings.click_consumer_group, message_id)

    def _dead_letter(self, message_id, fields: dict, reason: str) -> None:
        safe_fields = {str(k): (v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v))[:5000] for k, v in fields.items()}
        self.redis.xadd(self.settings.click_dead_letter_stream, {
            "source_message_id": str(message_id),
            "reason": reason[:300],
            "payload": json.dumps(safe_fields),
            "failed_at": str(time.time()),
        })
        self._ack(message_id)
        logger.error("click_event_dead_lettered", extra={"message_id": str(message_id), "reason": reason[:100]})

    def _delivery_count(self, message_id) -> int:
        try:
            entries = self.redis.xpending_range(
                self.settings.click_stream_name,
                self.settings.click_consumer_group,
                min=message_id,
                max=message_id,
                count=1,
            )
            return int(entries[0].get("times_delivered", 1)) if entries else 1
        except Exception:
            return 1

    def process_message(self, message_id, fields: dict) -> None:
        try:
            event = self._payload(fields)
        except Exception as exc:
            self._dead_letter(message_id, fields, f"invalid_event:{type(exc).__name__}")
            return
        db = self.session_factory()
        try:
            inserted = persist_event(db, event)
            self._ack(message_id)  # Acknowledge only after a committed insert or confirmed duplicate.
            logger.info("click_event_processed", extra={"event_id": str(event.event_id), "link_id": str(event.link_id), "inserted": inserted})
        except Exception as exc:
            db.rollback()
            deliveries = self._delivery_count(message_id)
            logger.error("click_event_processing_failed", extra={"event_id": str(event.event_id), "link_id": str(event.link_id), "error_type": type(exc).__name__, "deliveries": deliveries})
            if deliveries >= self.settings.worker_max_deliveries:
                self._dead_letter(message_id, fields, f"processing_failed:{type(exc).__name__}")
            # Otherwise leave pending; XAUTOCLAIM will recover it after the idle timeout.
        finally:
            db.close()

    def recover_pending(self) -> int:
        """Claim idle pending events using a bounded per-message exponential delay."""
        try:
            pending = self.redis.xpending_range(
                self.settings.click_stream_name,
                self.settings.click_consumer_group,
                min="-",
                max="+",
                count=max(100, self.settings.worker_batch_size * 10),
            )
        except Exception as exc:
            logger.warning("click_event_pending_scan_failed", extra={"error_type": type(exc).__name__})
            return 0

        recovered = 0
        base_ms = self.settings.worker_pending_idle_ms
        max_ms = self.settings.worker_max_backoff_seconds * 1000
        for entry in pending:
            if recovered >= self.settings.worker_batch_size:
                break
            message_id = entry.get("message_id")
            if message_id is None:
                continue
            deliveries = max(1, int(entry.get("times_delivered", 1)))
            backoff_ms = min(base_ms * (2 ** min(deliveries - 1, 20)), max_ms)
            idle_ms = int(entry.get("time_since_delivered", 0))
            if idle_ms < backoff_ms:
                continue
            try:
                claimed = self.redis.xclaim(
                    self.settings.click_stream_name,
                    self.settings.click_consumer_group,
                    self.consumer,
                    backoff_ms,
                    [message_id],
                )
            except Exception as exc:
                logger.warning("click_event_pending_claim_failed", extra={"message_id": str(message_id), "error_type": type(exc).__name__})
                continue
            for claimed_id, fields in claimed:
                self.process_message(claimed_id, fields)
                recovered += 1
        return recovered

    def run_forever(self, stop_event: Event | None = None) -> None:
        redis_failures = 0
        group_ready = False
        while stop_event is None or not stop_event.is_set():
            try:
                if not group_ready:
                    self.ensure_group()
                    group_ready = True
                self.recover_pending()
                batches = self.redis.xreadgroup(
                    self.settings.click_consumer_group,
                    self.consumer,
                    {self.settings.click_stream_name: ">"},
                    count=self.settings.worker_batch_size,
                    block=self.settings.worker_block_ms,
                )
                redis_failures = 0
                for _stream, messages in batches:
                    for message_id, fields in messages:
                        self.process_message(message_id, fields)
            except Exception as exc:
                redis_failures = min(redis_failures + 1, 6)
                delay = min(2 ** (redis_failures - 1), 30)
                logger.error("click_worker_stream_error", extra={"error_type": type(exc).__name__, "deliveries": redis_failures})
                if stop_event is not None:
                    if stop_event.wait(delay):
                        break
                else:
                    time.sleep(delay)
