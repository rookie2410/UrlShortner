import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.api.routes.links import get_runtime
from app.api.dependencies import RuntimeServices
from app.core.config import get_settings
from app.db.session import get_db
from app.repositories.links import get_link_by_code, is_link_unavailable
from app.schemas.links import ClickEventPayload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["redirects"])
_CODE_RE = re.compile(r"^[23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ]{7,16}$")


def _referrer_domain(referer: str | None) -> str | None:
    if not referer:
        return None
    try:
        host = urlsplit(referer).hostname
        if not host:
            return None
        return host[:255]
    except ValueError:
        return None


def _user_agent_family(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    agent = user_agent.lower()
    if "edg/" in agent:
        return "Edge"
    if "opr/" in agent or "opera" in agent:
        return "Opera"
    if "firefox/" in agent:
        return "Firefox"
    if "chrome/" in agent and "chromium" not in agent:
        return "Chrome"
    if "safari/" in agent and "chrome/" not in agent:
        return "Safari"
    if "curl/" in agent:
        return "curl"
    return "Other"


@router.get("/{code}", include_in_schema=False)
def resolve_short_link(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    runtime: RuntimeServices = Depends(get_runtime),
) -> RedirectResponse:
    if not _CODE_RE.fullmatch(code):
        raise HTTPException(status_code=404, detail={"code": "link_not_found", "message": "This short link was not found."})

    cached = runtime.cache.get(code)
    if cached is not None:
        destination = cached.original_url
        link_id = cached.link_id
        link_expires_at = cached.expires_at
    else:
        link = get_link_by_code(db, code)
        if link is None:
            raise HTTPException(status_code=404, detail={"code": "link_not_found", "message": "This short link was not found."})
        if is_link_unavailable(link):
            runtime.cache.delete(code)
            raise HTTPException(status_code=410, detail={"code": "link_unavailable", "message": "This short link has expired or been deactivated."})
        runtime.cache.set(link)
        destination = link.original_url
        link_id = str(link.id)
        link_expires_at = link.expires_at

    # Cache TTL is capped by expiration. Recheck the timestamp to handle boundary crossings.
    if link_expires_at is not None:
        expiry = link_expires_at if link_expires_at.tzinfo else link_expires_at.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            runtime.cache.delete(code)
            raise HTTPException(status_code=410, detail={"code": "link_unavailable", "message": "This short link has expired or been deactivated."})

    click = ClickEventPayload(
        event_id=uuid.uuid4(),
        link_id=uuid.UUID(str(link_id)),
        clicked_at=datetime.now(timezone.utc),
        referrer_domain=_referrer_domain(request.headers.get("referer")),
        user_agent_family=_user_agent_family(request.headers.get("user-agent")),
    )
    runtime.click_queue.enqueue(click)  # Best-effort: click analytics never blocks a redirect.
    return RedirectResponse(destination, status_code=302)
