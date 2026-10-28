from app.models import Link
from app.repositories.links import create_link
import app.repositories.links as repository


def test_short_code_collision_retries_with_new_value(db_factory, monkeypatch):
    with db_factory() as db:
        db.add(Link(code="AbCdEfG", original_url="https://existing.example", is_active=True))
        db.commit()
        codes = iter(["AbCdEfG", "XyZ2345"])
        monkeypatch.setattr(repository, "generate_short_code", lambda: next(codes))
        created = create_link(db, "https://new.example", None, max_attempts=2)
        assert created.code == "XyZ2345"


def test_repeated_collisions_stop_after_bounded_attempts(db_factory, monkeypatch):
    import pytest
    from app.repositories.links import ShortCodeExhaustedError

    with db_factory() as db:
        db.add(Link(code="AbCdEfG", original_url="https://existing.example", is_active=True))
        db.commit()
        monkeypatch.setattr(repository, "generate_short_code", lambda: "AbCdEfG")
        with pytest.raises(ShortCodeExhaustedError):
            create_link(db, "https://new.example", None, max_attempts=2)
