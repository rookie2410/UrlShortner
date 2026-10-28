from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.dependencies import RuntimeServices
from app.api.routes.links import get_runtime
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.schemas.links import ClickEventPayload


class MemoryCache:
    def __init__(self):
        self.items = {}

    def get(self, code):
        item = self.items.get(code)
        if item and item.expires_at and item.expires_at <= datetime.now(timezone.utc):
            self.items.pop(code, None)
            return None
        return item

    def set(self, link):
        from app.cache.redirect_cache import CachedRedirect
        self.items[link.code] = CachedRedirect(str(link.id), link.code, link.original_url, link.expires_at, link.is_active)

    def delete(self, code):
        self.items.pop(code, None)


class MemoryQueue:
    def __init__(self):
        self.events = []
        self.accept = True

    def enqueue(self, event: ClickEventPayload):
        if self.accept:
            self.events.append(event)
            return True
        return False


class AllowLimiter:
    def allow(self, key):
        return True


class FakeRedis:
    def ping(self):
        return True

    def close(self):
        pass


@pytest.fixture

def db_factory():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture

def client(db_factory):
    app = create_app()
    cache, queue = MemoryCache(), MemoryQueue()
    runtime = RuntimeServices(cache=cache, click_queue=queue, rate_limiter=AllowLimiter(), redis=FakeRedis())
    app.state.runtime = runtime

    def override_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, follow_redirects=False) as test_client:
        test_client.runtime = runtime
        yield test_client
    app.dependency_overrides.clear()
