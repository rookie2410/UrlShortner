import logging
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from app.api.dependencies import RuntimeServices, make_runtime
from app.core.config import get_settings
from app.db.session import get_db
from app.repositories.links import ShortCodeExhaustedError, create_link, deactivate_link, get_link_by_code, get_stats, is_link_unavailable
from app.schemas.links import CreateLinkRequest, LinkCreatedResponse, LinkStatsResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/links", tags=["links"])


def get_runtime(request: Request) -> RuntimeServices:
    return getattr(request.app.state, "runtime", None) or make_runtime()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.post("", response_model=LinkCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_short_link(
    payload: CreateLinkRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    runtime: RuntimeServices = Depends(get_runtime),
) -> LinkCreatedResponse:
    settings = get_settings()
    client_key = request.client.host if request.client else "unknown"
    if not runtime.rate_limiter.allow(client_key):
        raise HTTPException(status_code=429, detail={"code": "rate_limit_exceeded", "message": "Too many link-creation requests. Try again shortly."})
    try:
        link = create_link(db, payload.url, payload.expires_at)
    except ShortCodeExhaustedError as exc:
        logger.error("short_code_allocation_failed", extra={"request_id": getattr(request.state, "request_id", None)})
        raise HTTPException(status_code=503, detail={"code": "short_code_unavailable", "message": str(exc)}) from exc
    return LinkCreatedResponse(
        code=link.code,
        short_url=f"{settings.public_base_url}/{link.code}",
        original_url=link.original_url,
        created_at=_utc(link.created_at),
        expires_at=_utc(link.expires_at) if link.expires_at else None,
    )


@router.get("/{code}/stats", response_model=LinkStatsResponse)
def link_stats(code: str, db: Session = Depends(get_db)) -> LinkStatsResponse:
    if not (7 <= len(code) <= 16) or not code.isascii() or not code.isalnum():
        raise HTTPException(status_code=404, detail={"code": "link_not_found", "message": "This short link was not found."})
    link = get_link_by_code(db, code)
    if link is None:
        raise HTTPException(status_code=404, detail={"code": "link_not_found", "message": "This short link was not found."})
    if is_link_unavailable(link):
        raise HTTPException(status_code=410, detail={"code": "link_unavailable", "message": "This short link has expired or been deactivated."})
    total, recent = get_stats(db, link)
    return LinkStatsResponse(
        code=link.code,
        total_clicks=total,
        clicks_last_24_hours=recent,
        created_at=_utc(link.created_at),
        expires_at=_utc(link.expires_at) if link.expires_at else None,
    )


@router.post("/{code}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_short_link(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    runtime: RuntimeServices = Depends(get_runtime),
) -> Response:
    settings = get_settings()
    supplied_token = request.headers.get("x-admin-token", "")
    if not settings.admin_api_token:
        raise HTTPException(status_code=503, detail={"code": "deactivation_not_configured", "message": "Administrative link deactivation is not configured."})
    if not secrets.compare_digest(supplied_token, settings.admin_api_token):
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Administrative credentials are required."})
    link = get_link_by_code(db, code)
    if link is None:
        raise HTTPException(status_code=404, detail={"code": "link_not_found", "message": "This short link was not found."})
    deactivate_link(db, link)
    runtime.cache.delete(code)
    return Response(status_code=204)
