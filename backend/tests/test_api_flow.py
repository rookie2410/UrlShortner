from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.models import ClickEvent, Link
from app.worker.processor import persist_event


def test_create_redirect_and_stats_flow(client, db_factory):
    response = client.post("/api/v1/links", json={"url": "https://example.com/products", "expires_at": None})
    assert response.status_code == 201
    created = response.json()
    assert created["short_url"].endswith("/" + created["code"])

    with db_factory() as db:
        link = db.scalar(select(Link).where(Link.code == created["code"]))
        assert link is not None
        assert link.original_url == "https://example.com/products"

    redirect = client.get(f"/{created['code']}", headers={"user-agent": "Mozilla/5.0 Chrome/126.0", "referer": "https://news.example/story"})
    assert redirect.status_code == 302
    assert redirect.headers["location"] == "https://example.com/products"
    event = client.runtime.click_queue.events[0]
    assert event.referrer_domain == "news.example"
    assert event.user_agent_family == "Chrome"

    with db_factory() as db:
        assert persist_event(db, event) is True
        assert persist_event(db, event) is False

    stats = client.get(f"/api/v1/links/{created['code']}/stats")
    assert stats.status_code == 200
    assert stats.json()["total_clicks"] == 1
    assert stats.json()["clicks_last_24_hours"] == 1


def test_rejects_invalid_url(client):
    response = client.post("/api/v1/links", json={"url": "javascript:alert(1)"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_code_returns_404(client):
    response = client.get("/AbCdEfG")
    assert response.status_code == 404


def test_expired_link_returns_410(client, db_factory):
    with db_factory() as db:
        link = Link(code="AbCdEfG", original_url="https://example.com", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1), is_active=True)
        db.add(link)
        db.commit()
    response = client.get("/AbCdEfG")
    assert response.status_code == 410


def test_deactivated_link_returns_410(client, db_factory):
    with db_factory() as db:
        db.add(Link(code="AbCdEfG", original_url="https://example.com", is_active=False))
        db.commit()
    response = client.get("/AbCdEfG")
    assert response.status_code == 410


def test_queue_failure_does_not_break_redirect(client):
    response = client.post("/api/v1/links", json={"url": "https://example.com"})
    code = response.json()["code"]
    client.runtime.click_queue.accept = False
    redirect = client.get(f"/{code}")
    assert redirect.status_code == 302


def test_health_is_lightweight(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_deactivation_requires_admin_token_and_invalidates_cache(client, monkeypatch):
    import app.api.routes.links as links_module
    from app.core.config import Settings

    created = client.post("/api/v1/links", json={"url": "https://example.com"}).json()
    monkeypatch.setattr(links_module, "get_settings", lambda: Settings(admin_api_token="test-admin-secret"))

    denied = client.post(f"/api/v1/links/{created['code']}/deactivate")
    assert denied.status_code == 403
    accepted = client.post(f"/api/v1/links/{created['code']}/deactivate", headers={"X-Admin-Token": "test-admin-secret"})
    assert accepted.status_code == 204
    assert client.get(f"/{created['code']}").status_code == 410


def test_oversized_request_is_rejected_before_validation(client):
    response = client.post("/api/v1/links", content="{}", headers={"Content-Type": "application/json", "Content-Length": "20000"})
    assert response.status_code == 413


def test_readiness_requires_redis_but_health_stays_lightweight(client):
    def fail_ping():
        raise TimeoutError("Redis offline")
    client.runtime.redis.ping = fail_ping
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503


def test_created_link_returns_zero_click_stats(client):
    created = client.post("/api/v1/links", json={"url": "https://example.com"}).json()
    stats = client.get(f"/api/v1/links/{created['code']}/stats")
    assert stats.status_code == 200
    assert stats.json()["total_clicks"] == 0
    assert stats.json()["clicks_last_24_hours"] == 0
