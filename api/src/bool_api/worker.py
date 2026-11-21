"""Worker service. Run with: uvicorn --factory bool_api.worker:create_app

Background jobs are pushed here by QStash. Requests are authenticated by
QStash signature verification (added in S1-07), not by X-Internal-Secret.
Until then the worker service is deployed without public access.
"""

import logging

from fastapi import FastAPI

from bool_api.config import Settings
from bool_api.logging_setup import configure_logging

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Bool Worker", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
