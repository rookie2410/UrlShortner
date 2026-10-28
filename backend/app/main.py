import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api.dependencies import make_runtime
from app.api.routes.health import router as health_router
from app.api.routes.links import router as links_router
from app.api.routes.redirect import router as redirect_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        runtime = getattr(app.state, "runtime", None)
        if runtime is not None:
            try:
                runtime.redis.close()
            except Exception:
                pass
        dispose_engine()

    app = FastAPI(title=settings.app_name, version="1.0.0", description="URL shortening and asynchronous click analytics API", lifespan=lifespan)
    app.state.runtime = make_runtime(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID", "X-Admin-Token"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdecimal() and int(content_length) > min(16384, max(4096, settings.max_url_length * 2)):
            response = JSONResponse(status_code=413, content={"error": {"code": "request_too_large", "message": "Request body exceeds the allowed size."}})
            response.headers["X-Request-ID"] = request_id
            logger.info("request_completed", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
            return response
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled_request_error", extra={"request_id": request_id})
            response = JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "An unexpected error occurred."}})
        response.headers["X-Request-ID"] = request_id
        logger.info("request_completed", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            error = detail
        else:
            mapping = {404: ("not_found", "The requested resource was not found."), 405: ("method_not_allowed", "This method is not allowed."), 429: ("rate_limit_exceeded", "Too many requests."), 410: ("gone", "This resource is no longer available.")}
            code, message = mapping.get(exc.status_code, ("request_error", str(detail) if isinstance(detail, str) else "The request could not be completed."))
            error = {"code": code, "message": message}
        return JSONResponse(status_code=exc.status_code, content={"error": error}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = []
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", []) if part != "body")
            errors.append({"field": location or "request", "message": item.get("msg", "Invalid value")})
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Please correct the highlighted fields.", "details": errors}})

    app.include_router(health_router)
    app.include_router(links_router)
    app.include_router(redirect_router)

    return app


app = create_app()
