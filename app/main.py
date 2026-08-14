from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api import auth, health, pages
from app.api.deps import LoginRedirect, login_redirect_handler
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.core.bootstrap import run_migrations
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)
BASE_DIR = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    logger.info(
        "Subindo editor Bolso Coberto",
        extra={"version": __version__, "environment": settings.environment},
    )
    if settings.run_migrations_on_startup:
        await run_migrations()
        configure_logging(settings.log_level)
    else:
        logger.warning("Migrations desabilitadas por configuração")
    try:
        yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.api_title,
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
        root_path=settings.root_path,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value() or "dev-only-not-for-prod",
        session_cookie="bolso_editor",
        https_only=settings.is_production,
        same_site="lax",
        max_age=60 * 60 * 12,
    )
    register_exception_handlers(app)
    app.add_exception_handler(LoginRedirect, login_redirect_handler)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(pages.router)

    static_dir = BASE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/robots.txt", include_in_schema=False)
    async def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    return app


app = create_app()
