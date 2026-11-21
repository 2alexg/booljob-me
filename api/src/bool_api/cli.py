"""Operator commands. Reads the same BOOL_* settings as the services.

python -m bool_api.cli publish <job> [--payload JSON] [--retries N]
"""

import argparse
import asyncio
import json
import sys

import httpx

from bool_api.config import Settings
from bool_api.jobs import REGISTRY
from bool_api.qstash import QStashClient
from bool_api.worker import FAILURE_PATH


async def publish(job: str, payload: dict[str, object], retries: int | None) -> str:
    settings = Settings()
    if settings.qstash_token is None or settings.worker_public_url is None:
        sys.exit("BOOL_QSTASH_TOKEN and BOOL_WORKER_PUBLIC_URL are required")
    if job not in REGISTRY:
        sys.exit(f"unknown job {job!r}; known: {', '.join(sorted(REGISTRY))}")
    base = settings.worker_public_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10) as http:
        client = QStashClient(settings.qstash_url, settings.qstash_token.get_secret_value(), http)
        return await client.publish(
            f"{base}/jobs/{job}",
            payload,
            retries=settings.job_max_retries if retries is None else retries,
            failure_callback=f"{base}{FAILURE_PATH}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="bool_api.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish", help="publish a job to the worker via QStash")
    pub.add_argument("job")
    pub.add_argument("--payload", default="{}", help="JSON object")
    pub.add_argument("--retries", type=int, default=None)
    args = parser.parse_args()

    payload = json.loads(args.payload)
    if not isinstance(payload, dict):
        sys.exit("--payload must be a JSON object")
    message_id = asyncio.run(publish(args.job, payload, args.retries))
    print(message_id)


if __name__ == "__main__":
    main()
