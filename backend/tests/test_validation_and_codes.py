import pytest
from pydantic import ValidationError
from app.schemas.links import CreateLinkRequest, validate_destination_url
from app.services.short_codes import ALPHABET, generate_short_code


def test_accepts_http_and_https_urls():
    assert validate_destination_url("https://example.com/products?q=one") == "https://example.com/products?q=one"
    assert validate_destination_url("http://localhost:8080/path") == "http://localhost:8080/path"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "ftp://example.com", "https://user:pass@example.com", "https://",
    "https://example.com/a b", "https://example.com:99999/path", "http://[invalid",
])
def test_rejects_invalid_or_unsafe_urls(url):
    with pytest.raises((ValueError, ValidationError)):
        validate_destination_url(url)


def test_expiration_must_be_timezone_aware_and_future():
    with pytest.raises(ValidationError):
        CreateLinkRequest(url="https://example.com", expires_at="2035-01-01T00:00:00")


def test_short_codes_are_seven_secure_url_safe_characters():
    code = generate_short_code()
    assert len(code) == 7
    assert all(character in ALPHABET for character in code)
    assert generate_short_code(12) != generate_short_code(12)


def test_short_code_length_is_bounded():
    with pytest.raises(ValueError):
        generate_short_code(17)


def test_comma_separated_cors_origins_parse():
    from app.core.config import Settings
    settings = Settings(allowed_frontend_origins="http://localhost:5173, https://app.example/")
    assert settings.allowed_frontend_origins == ["http://localhost:5173", "https://app.example"]


def test_rejects_malformed_hostname():
    with pytest.raises(ValueError):
        validate_destination_url("https://bad_host.example/path")


def test_rejects_non_http_public_base_url():
    from pydantic import ValidationError
    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(public_base_url="javascript:alert(1)")
