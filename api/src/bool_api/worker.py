"""Worker service. Run with: uvicorn --factory bool_api.worker:create_app

QStash pushes jobs to POST /jobs/<name> and, once a job has exhausted its
retries, calls POST /qstash/failure. Both endpoints accept only requests
carrying a valid QStash signature for their exact URL. There is no
X-Internal-Secret here: the worker is reachable from the internet, and the
signature is what authenticates the caller.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from bool_api.alerts import Alerter, build_alerter
from bool_api.config import Settings
from bool_api.jobs import SCHEDULE_PREFIX, SCHEDULES, JobContext, resolve
from bool_api.logging_setup import configure_logging
from bool_api.qstash import QStashClient, QStashSignatureError, SignatureVerifier

log = logging.getLogger(__name__)

FAILURE_PATH = "/qstash/failure"


async def sync_schedules(
    qstash: QStashClient, base_url: str, retries: int, alerter: Alerter
) -> None:
    """Make QStash's schedules match SCHEDULES: upsert ours, delete stale ones."""
    try:
        wanted = set()
        for schedule in SCHEDULES:
            await qstash.upsert_schedule(
                schedule.id,
                f"{base_url}/jobs/{schedule.job}",
                schedule.cron,
                retries=retries,
                failure_callback=f"{base_url}{FAILURE_PATH}",
            )
            wanted.add(schedule.id)
        for existing in await qstash.list_schedules():
            schedule_id = str(existing.get("scheduleId", ""))
            if schedule_id.startswith(SCHEDULE_PREFIX) and schedule_id not in wanted:
                await qstash.delete_schedule(schedule_id)
                log.info("deleted stale schedule", extra={"schedule_id": schedule_id})
        log.info("schedules synced", extra={"count": len(wanted)})
    except Exception:
        log.exception("schedule sync failed")
        with suppress(Exception):
            await alerter.send("schedule_sync_failed")


def create_app(
    settings: Settings | None = None,
    *,
    http: httpx.AsyncClient | None = None,
    alerter: Alerter | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    base_url = settings.worker_public_url.rstrip("/") if settings.worker_public_url else None
    verifier = None
    if settings.qstash_current_signing_key and settings.qstash_next_signing_key:
        verifier = SignatureVerifier(
            settings.qstash_current_signing_key.get_secret_value(),
            settings.qstash_next_signing_key.get_secret_value(),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = http or httpx.AsyncClient(timeout=10)
        app.state.alerter = alerter or build_alerter(settings, client)
        sync_task = None
        if settings.qstash_token and base_url:
            qstash = QStashClient(
                settings.qstash_url, settings.qstash_token.get_secret_value(), client
            )
            sync_task = asyncio.create_task(
                sync_schedules(qstash, base_url, settings.job_max_retries, app.state.alerter)
            )
        log.info(
            "worker started",
            extra={
                "environment": settings.environment,
                "signature_check": verifier is not None and base_url is not None,
                "schedule_sync": sync_task is not None,
            },
        )
        try:
            yield
        finally:
            if sync_task is not None and not sync_task.done():
                sync_task.cancel()
            if http is None:
                await client.aclose()

    app = FastAPI(
        title="Bool Worker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings

    async def verified_body(request: Request, path: str) -> bytes:
        if verifier is None or base_url is None:
            # Fail closed: without keys nothing can be authenticated.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "QStash is not configured")
        body = await request.body()
        try:
            verifier.verify(request.headers.get("upstash-signature"), body, f"{base_url}{path}")
        except QStashSignatureError as e:
            log.warning("rejected QStash request", extra={"path": path, "reason": str(e)})
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature") from e
        return body

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/jobs/{name}")
    async def run_job(name: str, request: Request) -> JSONResponse:
        body = await verified_body(request, f"/jobs/{name}")
        spec = resolve(name, settings.environment)
        if spec is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")
        try:
            payload = json.loads(body) if body else {}
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be JSON") from e
        if not isinstance(payload, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be a JSON object")

        retried_header = request.headers.get("upstash-retried", "0")
        ctx = JobContext(
            settings=settings,
            alerter=request.app.state.alerter,
            message_id=request.headers.get("upstash-message-id"),
            retried=int(retried_header) if retried_header.isdigit() else 0,
        )
        try:
            await spec.handler(payload, ctx)
        except Exception:
            log.exception(
                "job failed",
                extra={"job": name, "message_id": ctx.message_id, "retried": ctx.retried},
            )
            # Non-2xx makes QStash retry; the last failure lands in the DLQ.
            return JSONResponse({"detail": "Job failed"}, status_code=500)
        return JSONResponse({"status": "ok"})

    @app.post(FAILURE_PATH)
    async def failure_callback(request: Request) -> dict[str, str]:
        body = await verified_body(request, FAILURE_PATH)
        data = json.loads(body)
        url = str(data.get("url", ""))
        jobs_prefix = f"{base_url}/jobs/"
        await request.app.state.alerter.send(
            "job_failed",
            job=url.removeprefix(jobs_prefix) if url.startswith(jobs_prefix) else None,
            message_id=data.get("sourceMessageId"),
            dlq_id=data.get("dlqId"),
            status=data.get("status"),
            retried=data.get("retried"),
            max_retries=data.get("maxRetries"),
            schedule_id=data.get("scheduleId"),
        )
        return {"status": "ok"}

    return app
