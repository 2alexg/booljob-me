"""Background job registry, handlers, and schedules.

A job is an async function registered under a dotted name. QStash delivers
it to the worker at POST /jobs/<name>. Raising an exception makes the worker
answer 500, so QStash retries; after the last retry the message goes to the
QStash dead-letter queue and the failure callback sends an admin alert.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from bool_api.alerts import Alerter
from bool_api.config import Settings

log = logging.getLogger(__name__)

JOB_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True)
class JobContext:
    settings: Settings
    alerter: Alerter
    message_id: str | None
    retried: int


JobHandler = Callable[[dict[str, Any], JobContext], Awaitable[None]]


@dataclass(frozen=True)
class JobSpec:
    name: str
    handler: JobHandler
    # Debug jobs exist for testing the pipeline and are refused in prod.
    debug_only: bool = False


REGISTRY: dict[str, JobSpec] = {}


def job(name: str, *, debug_only: bool = False) -> Callable[[JobHandler], JobHandler]:
    if not JOB_NAME.match(name):
        raise ValueError(f"invalid job name {name!r}")

    def register(handler: JobHandler) -> JobHandler:
        if name in REGISTRY:
            raise ValueError(f"job {name!r} registered twice")
        REGISTRY[name] = JobSpec(name, handler, debug_only)
        return handler

    return register


def resolve(name: str, environment: str) -> JobSpec | None:
    spec = REGISTRY.get(name)
    if spec is None or (spec.debug_only and environment == "prod"):
        return None
    return spec


# --- Handlers ---------------------------------------------------------------


@job("debug.ping", debug_only=True)
async def debug_ping(payload: dict[str, Any], ctx: JobContext) -> None:
    log.info("debug.ping", extra={"message_id": ctx.message_id, "retried": ctx.retried})


@job("debug.fail", debug_only=True)
async def debug_fail(payload: dict[str, Any], ctx: JobContext) -> None:
    raise RuntimeError("intentional failure (tests retries, dead-letter queue and alerts)")


@job("system.heartbeat")
async def system_heartbeat(payload: dict[str, Any], ctx: JobContext) -> None:
    # Daily proof that schedules fire and alerts arrive.
    await ctx.alerter.send("worker_heartbeat", message_id=ctx.message_id)


# --- Schedules --------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    id: str  # stable id; QStash upserts by it
    job: str
    cron: str


SCHEDULE_PREFIX = "bool-"

# Israel time, so "nightly" means night in Israel. Ingestion and match expiry
# are added with their handlers (S1-16 and the lifecycle worker).
SCHEDULES = (
    Schedule("bool-system-heartbeat", "system.heartbeat", "CRON_TZ=Asia/Jerusalem 0 9 * * *"),
)
