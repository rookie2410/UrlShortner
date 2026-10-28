from dataclasses import dataclass
from typing import Any
from app.cache.redirect_cache import RedirectCache
from app.core.config import Settings, get_settings
from app.queue.click_queue import ClickEventQueue
from app.services.rate_limiter import CreateRateLimiter
from app.services.redis_circuit_breaker import RedisCircuitBreaker


@dataclass
class RuntimeServices:
    cache: RedirectCache
    click_queue: ClickEventQueue
    rate_limiter: CreateRateLimiter
    redis: Any


def make_runtime(settings: Settings | None = None, *, socket_timeout_seconds: float | None = None) -> RuntimeServices:
    settings = settings or get_settings()
    try:
        from redis import Redis
        timeout = socket_timeout_seconds if socket_timeout_seconds is not None else settings.redis_socket_timeout_seconds
        redis_client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            socket_timeout=timeout,
            decode_responses=True,
            health_check_interval=30,
        )
    except ImportError:
        # Lets isolated unit tests import the API when optional service dependencies
        # have not been installed; production installs redis via pyproject.toml.
        class UnavailableRedis:
            def __getattr__(self, name):
                raise RuntimeError("Redis client dependency is not installed")
            def close(self):
                pass
        redis_client = UnavailableRedis()
    return RuntimeServices(
        cache=RedirectCache(redis_client, settings, RedisCircuitBreaker()),
        click_queue=ClickEventQueue(redis_client, settings, RedisCircuitBreaker()),
        rate_limiter=CreateRateLimiter(redis_client, settings, RedisCircuitBreaker()),
        redis=redis_client,
    )
