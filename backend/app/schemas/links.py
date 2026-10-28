import ipaddress
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.core.config import get_settings


def validate_destination_url(value: str) -> str:
    settings = get_settings()
    if not isinstance(value, str):
        raise ValueError("Enter a valid URL.")
    value = value.strip()
    if not value or len(value) > settings.max_url_length:
        raise ValueError(f"URL must be between 1 and {settings.max_url_length} characters.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value) or any(ch.isspace() for ch in value):
        raise ValueError("URL must not contain whitespace or control characters.")
    try:
        parsed = urlsplit(value)
        # Accessing .port also validates an invalid/out-of-range port.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid URL.") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are allowed.")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    hostname = parsed.hostname
    if hostname.startswith(".") or hostname.endswith(".") or ".." in hostname:
        raise ValueError("Enter a valid hostname.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            ascii_host = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Enter a valid hostname.") from exc
        if len(ascii_host) > 253:
            raise ValueError("Enter a valid hostname.")
        labels = ascii_host.split(".")
        label_pattern = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
        if any(len(label) > 63 or not label_pattern.fullmatch(label) for label in labels):
            raise ValueError("Enter a valid hostname.")
    return value


def ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Expiration timestamp must include a timezone, such as Z or +00:00.")
    value = value.astimezone(timezone.utc)
    if value <= datetime.now(timezone.utc):
        raise ValueError("Expiration must be in the future.")
    return value


class CreateLinkRequest(BaseModel):
    url: str = Field(min_length=1)
    expires_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def url_must_be_safe_format(cls, value: str) -> str:
        return validate_destination_url(value)

    @field_validator("expires_at")
    @classmethod
    def expiration_must_be_future_and_aware(cls, value: datetime | None) -> datetime | None:
        return ensure_aware_utc(value)


class LinkCreatedResponse(BaseModel):
    code: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None


class LinkStatsResponse(BaseModel):
    code: str
    total_clicks: int
    clicks_last_24_hours: int
    created_at: datetime
    expires_at: datetime | None


class ApiError(BaseModel):
    error: dict[str, object]


class ClickEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    link_id: uuid.UUID
    clicked_at: datetime
    referrer_domain: str | None = Field(default=None, max_length=255)
    user_agent_family: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def normalize_click_time(self):
        if self.clicked_at.tzinfo is None or self.clicked_at.utcoffset() is None:
            raise ValueError("clicked_at must include a timezone")
        self.clicked_at = self.clicked_at.astimezone(timezone.utc)
        return self
