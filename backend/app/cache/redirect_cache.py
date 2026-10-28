import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from app.core.config import Settings
from app.models import Link
from app.services.redis_circuit_breaker import RedisCircuitBreaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedRedirect:
    link_id: str
    code: str
    original_url: str
    expires_at: datetime | None
    is_active: bool


class RedirectCache:
    def __init__(self, redis: Any, settings: Settings, circuit_breaker: RedisCircuitBreaker | None = None):
        self.redis = redis
        self.settings = settings
        self.circuit_breaker = circuit_breaker or RedisCircuitBreaker()

    @staticmethod
    def key(code: str) -> str:
        return f"shortlink:redirect:{code}"

    def get(self, code: str) -> CachedRedirect | None:
        if not self.circuit_breaker.allow_request():
            return None
        try:
            raw = self.redis.get(self.key(code))
            self.circuit_breaker.record_success()
            if not raw:
                return None
            value = json.loads(raw)
            expires_at = datetime.fromisoformat(value["expires_at"]) if value.get("expires_at") else None
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            item = CachedRedirect(
                link_id=str(value["link_id"]),
                code=str(value["code"]),
                original_url=str(value["original_url"]),
                expires_at=expires_at,
                is_active=bool(value["is_active"]),
            )
            if not item.is_active or (item.expires_at and item.expires_at <= datetime.now(timezone.utc)):
                self.delete(code)
                return None
            return item
        except Exception as exc:  # Cache is best-effort; PostgreSQL remains authoritative.
            self.circuit_breaker.record_failure()
            logger.warning("redirect_cache_read_failed", extra={"code": code, "error_type": type(exc).__name__})
            return None

    def set(self, link: Link) -> None:
        now = datetime.now(timezone.utc)
        ttl = self.settings.redirect_cache_ttl_seconds
        if not link.is_active:
            return
        if link.expires_at is not None:
            expires_at = link.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            remaining = (expires_at - now).total_seconds()
            if remaining <= 0:
                return
            ttl = min(ttl, max(1, math.floor(remaining)))
        value = {
            "link_id": str(link.id),
            "code": link.code,
            "original_url": link.original_url,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "is_active": link.is_active,
        }
        if not self.circuit_breaker.allow_request():
            return
        try:
            self.redis.set(self.key(link.code), json.dumps(value), ex=ttl)
            self.circuit_breaker.record_success()
        except Exception as exc:
            self.circuit_breaker.record_failure()
            logger.warning("redirect_cache_write_failed", extra={"code": link.code, "error_type": type(exc).__name__})

    def delete(self, code: str) -> None:
        # Invalidation bypasses the open-circuit gate because revocation is security-sensitive.
        try:
            self.redis.delete(self.key(code))
            self.circuit_breaker.record_success()
        except Exception as exc:
            self.circuit_breaker.record_failure()
            logger.warning("redirect_cache_invalidation_failed", extra={"code": code, "error_type": type(exc).__name__})
