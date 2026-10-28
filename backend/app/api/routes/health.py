from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.routes.links import get_runtime
from app.api.dependencies import RuntimeServices
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(
    request: Request,
    db: Session = Depends(get_db),
    runtime: RuntimeServices = Depends(get_runtime),
) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        runtime.redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "not_ready", "message": "Required application dependencies are unavailable."}) from exc
    return {"status": "ready"}
