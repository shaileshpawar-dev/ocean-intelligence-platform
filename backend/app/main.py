"""FastAPI application entrypoint.

Composition root: configure logging, create tables, register middleware and
mount routers. No business logic lives here.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    analytics,
    health,
    intelligence,
    ml,
    pollution,
    satellite,
)
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.logging import configure_logging, get_logger, new_request_id, set_request_id

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down hooks."""
    init_db()
    logger.info(
        "startup",
        extra={
            "environment": settings.environment,
            "demo_mode": settings.demo_mode,
            "detector_backend": settings.detector_backend,
            "gee_configured": settings.gee_configured,
        },
    )

    # Seed regions and the model registry so a fresh database is immediately
    # usable. Ingestion is left to an explicit call so start-up stays fast.
    with SessionLocal() as db:
        from app.demo.seed import bootstrap
        from app.rag.service import ingest_seed_corpus

        bootstrap(db)
        ingest_seed_corpus(db)

    yield
    logger.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    summary=(
        "Satellite-based ocean pollution intelligence: SAR dark-formation "
        "detection, temporal analytics, explainable risk scoring and "
        "forecasting, with explicit provenance on every claim."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Bind a request id, time the request and log the outcome.

    The id is echoed as ``X-Request-ID`` so a user-reported problem can be
    traced straight to its log lines.
    """
    incoming = request.headers.get("x-request-id")
    request_id = incoming or new_request_id()
    set_request_id(request_id)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={"method": request.method, "path": request.url.path},
        )
        raise
    duration_ms = (time.perf_counter() - started) * 1000

    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a uniform error body without leaking internals to the client."""
    logger.exception("unhandled_exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "detail": "An unexpected error occurred. Check server logs.",
            "request_id": request.headers.get("x-request-id"),
        },
    )


API_PREFIX = "/api/v1"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(pollution.router, prefix=API_PREFIX)
app.include_router(satellite.router, prefix=API_PREFIX)
app.include_router(analytics.router, prefix=API_PREFIX)
app.include_router(ml.router, prefix=API_PREFIX)
app.include_router(intelligence.router, prefix=API_PREFIX)


@app.get("/preview", tags=["system"], include_in_schema=False)
def preview() -> FileResponse:
    """Serve the built-in preview dashboard.

    A single self-contained page that reads the live API from the same
    origin. It exists so the platform is inspectable without running a
    separate frontend, and so the provenance contract -- the simulated-data
    banner, the evidence badges, the risk contribution bars -- is visible
    rather than buried in JSON.
    """
    return FileResponse(Path(__file__).parent / "static" / "preview.html")


# ---------------------------------------------------------------------------
# OceanAI console (React SPA)
#
# The SPA is built by Vite into ``app/static/app`` and served from here, so the
# runtime container stays pure Python -- Node is a build-time dependency only.
# Hashed assets are mounted directly; every other /app path falls through to
# index.html because the router uses browser history, and a deep link such as
# /app/events/evt_123 must reach React rather than 404 at the server.
# ---------------------------------------------------------------------------
SPA_DIR = Path(__file__).parent / "static" / "app"
SPA_INDEX = SPA_DIR / "index.html"

# Cache policy, and why it matters on a rolling deploy:
#
# Vite content-hashes every asset filename, so an asset URL never changes
# meaning and can be cached indefinitely. index.html is the opposite: its
# content changes on every build because it names the new hashes. Cache it and
# a returning browser asks for chunk files the new deployment no longer has,
# and the app dies with "Failed to fetch dynamically imported module" -- while
# the server looks perfectly healthy.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache, no-store, must-revalidate"


class _HashedAssets(StaticFiles):
    """StaticFiles that marks content-hashed assets immutable."""

    def file_response(self, *args: object, **kwargs: object) -> Response:
        """Attach a long-lived cache header to every asset served."""
        response = super().file_response(*args, **kwargs)  # type: ignore[arg-type]
        response.headers["Cache-Control"] = IMMUTABLE_CACHE
        return response


if (SPA_DIR / "assets").is_dir():
    app.mount(
        "/app/assets",
        _HashedAssets(directory=SPA_DIR / "assets"),
        name="oceanai-assets",
    )


@app.get("/app", include_in_schema=False, response_model=None)
@app.get("/app/{spa_path:path}", include_in_schema=False, response_model=None)
def oceanai_console(spa_path: str = "") -> FileResponse | JSONResponse:
    """Serve the OceanAI console, or an actionable message if it is not built."""
    # Static files that genuinely exist (favicon and similar) are served as-is.
    if spa_path:
        candidate = (SPA_DIR / spa_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(SPA_DIR.resolve()):
            return FileResponse(candidate)

    if not SPA_INDEX.is_file():
        return JSONResponse(
            status_code=503,
            content={
                "error": "console_not_built",
                "detail": (
                    "The OceanAI console has not been built. Run "
                    "`npm install && npm run build` in frontend/, which emits "
                    "into backend/app/static/app. The API itself is "
                    "unaffected and remains available at /api/v1."
                ),
            },
        )
    # Never cache the entry document: it names this build's chunk hashes.
    return FileResponse(SPA_INDEX, headers={"Cache-Control": NO_CACHE})


@app.get("/", tags=["system"], summary="Service banner", response_model=None)
def root(request: Request) -> RedirectResponse | dict:
    """Service descriptor, or the console for a browser.

    Content-negotiated on purpose. A browser asking for HTML is sent to the
    console; anything else -- curl, a health probe, an SDK -- still receives
    the JSON descriptor it received before the console existed. Redirecting
    unconditionally would have broken every existing API client.
    """
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html and SPA_INDEX.is_file():
        return RedirectResponse(url="/app", status_code=307)

    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "demo_mode": settings.demo_mode,
        "docs": "/docs",
        "api": API_PREFIX,
        "console": "/app" if SPA_INDEX.is_file() else "not built",
    }
