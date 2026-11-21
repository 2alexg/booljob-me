"""API service. Run with: uvicorn --factory bool_api.main:create_app"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status

from bool_api import db
from bool_api.auth import CurrentUser, TokenVerifier
from bool_api.config import Settings
from bool_api.internal_secret import InternalSecretMiddleware
from bool_api.logging_setup import configure_logging

log = logging.getLogger(__name__)

# Liveness only; reveals nothing. Everything else requires X-Internal-Secret.
PUBLIC_PATHS = frozenset({"/healthz"})


def create_app(
    settings: Settings | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    if settings.internal_secret is None:
        raise RuntimeError("BOOL_INTERNAL_SECRET is required for the API service")

    if token_verifier is None and settings.jwks_url and settings.jwt_issuer:
        token_verifier = TokenVerifier.from_jwks_url(
            settings.jwks_url, settings.jwt_issuer, settings.jwt_audience
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = None
        if settings.database_url is not None:
            pool = db.create_pool(settings.database_url.get_secret_value())
            await pool.open(wait=False)
        app.state.db_pool = pool
        log.info(
            "api started",
            extra={
                "environment": settings.environment,
                "auth_configured": token_verifier is not None,
                "db_configured": pool is not None,
            },
        )
        try:
            yield
        finally:
            if pool is not None:
                await pool.close()

    app = FastAPI(
        title="Bool API",
        lifespan=lifespan,
        # No public API docs; this service sits behind the BFF.
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment in ("local", "test") else None,
    )
    app.state.settings = settings
    app.state.token_verifier = token_verifier
    app.state.db_pool = None
    app.add_middleware(
        InternalSecretMiddleware,
        secret=settings.internal_secret.get_secret_value(),
        exempt_paths=PUBLIC_PATHS,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> dict[str, str]:
        pool = request.app.state.db_pool
        if pool is None:
            return {"status": "ok", "database": "not_configured"}
        try:
            await db.ping(pool)
        except Exception as e:
            log.exception("database ping failed")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from e
        return {"status": "ok", "database": "ok"}

    @app.get("/v1/me")
    def me(user: CurrentUser) -> dict[str, str]:
        return {"user_id": str(user.id), "role": user.role}

    return app
