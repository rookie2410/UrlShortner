from datetime import datetime, timezone, timedelta
import json
from app.cache.redirect_cache import RedirectCache
from app.core.config import Settings
from app.models import Link


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.fail = False

    def set(self, key, value, ex):
        if self.fail: raise TimeoutError("test timeout")
        self.values[key] = value
        self.ttls[key] = ex

    def get(self, key):
        if self.fail: raise TimeoutError("test timeout")
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


def test_cache_key_and_value():
    redis = FakeRedis()
    cache = RedirectCache(redis, Settings(redirect_cache_ttl_seconds=300))
    link = Link(code="AbCdEfG", original_url="https://example.com", is_active=True)
    cache.set(link)
    assert cache.key("AbCdEfG") == "shortlink:redirect:AbCdEfG"
    assert cache.get("AbCdEfG").original_url == "https://example.com"


def test_cache_ttl_is_capped_by_expiration():
    redis = FakeRedis()
    cache = RedirectCache(redis, Settings(redirect_cache_ttl_seconds=300))
    link = Link(code="AbCdEfG", original_url="https://example.com", expires_at=datetime.now(timezone.utc) + timedelta(seconds=20), is_active=True)
    cache.set(link)
    assert 1 <= redis.ttls[cache.key("AbCdEfG")] <= 20


def test_redis_failure_is_a_cache_miss():
    redis = FakeRedis(); redis.fail = True
    cache = RedirectCache(redis, Settings())
    assert cache.get("AbCdEfG") is None


def test_invalidation_deletes_cached_mapping():
    redis = FakeRedis()
    cache = RedirectCache(redis, Settings())
    link = Link(code="AbCdEfG", original_url="https://example.com", is_active=True)
    cache.set(link)
    cache.delete("AbCdEfG")
    assert cache.get("AbCdEfG") is None
