import json

import httpx
import pytest
from fastapi.testclient import TestClient

from bool_api import jobs
from bool_api.config import Settings
from bool_api.jobs import REGISTRY, SCHEDULES, resolve
from bool_api.qstash import QStashClient
from bool_api.worker import create_app, sync_schedules
from tests.test_qstash import CURRENT, NEXT, sign

BASE = "https://worker.example"


class FakeAlerter:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, object]]] = []

    async def send(self, event: str, **fields: object) -> None:
        self.sent.append((event, fields))


def worker_settings(**overrides) -> Settings:
    values = {
        "environment": "test",
        "qstash_current_signing_key": CURRENT,
        "qstash_next_signing_key": NEXT,
        "worker_public_url": BASE,
        **overrides,
    }
    return Settings(**values)


@pytest.fixture
def alerter() -> FakeAlerter:
    return FakeAlerter()


@pytest.fixture
def client(alerter):
    app = create_app(worker_settings(), alerter=alerter)
    with TestClient(app) as c:
        yield c


def post_signed(client: TestClient, path: str, body: bytes = b"{}", **headers: str):
    signature = sign(CURRENT, f"{BASE}{path}", body)
    return client.post(path, content=body, headers={"Upstash-Signature": signature, **headers})


# --- Jobs -------------------------------------------------------------------


def test_signed_job_runs(client) -> None:
    response = post_signed(client, "/jobs/debug.ping", b'{"x":1}')
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_failing_job_returns_500_so_qstash_retries(client) -> None:
    response = post_signed(client, "/jobs/debug.fail", **{"Upstash-Retried": "1"})
    assert response.status_code == 500


def test_unsigned_request_rejected(client) -> None:
    assert client.post("/jobs/debug.ping", content=b"{}").status_code == 401


def test_signature_for_another_job_rejected(client) -> None:
    signature = sign(CURRENT, f"{BASE}/jobs/debug.ping", b"{}")
    response = client.post(
        "/jobs/debug.fail", content=b"{}", headers={"Upstash-Signature": signature}
    )
    assert response.status_code == 401


def test_unknown_job(client) -> None:
    assert post_signed(client, "/jobs/no.such_job").status_code == 404


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]"])
def test_body_must_be_a_json_object(client, body) -> None:
    assert post_signed(client, "/jobs/debug.ping", body).status_code == 400


def test_debug_jobs_refused_in_prod(alerter) -> None:
    app = create_app(worker_settings(environment="prod"), alerter=alerter)
    with TestClient(app) as c:
        assert post_signed(c, "/jobs/debug.fail").status_code == 404
        assert post_signed(c, "/jobs/system.heartbeat").status_code == 200


def test_fails_closed_without_keys(alerter) -> None:
    app = create_app(Settings(environment="test", worker_public_url=BASE), alerter=alerter)
    with TestClient(app) as c:
        assert post_signed(c, "/jobs/debug.ping").status_code == 503


def test_heartbeat_sends_an_alert(client, alerter) -> None:
    post_signed(client, "/jobs/system.heartbeat", **{"Upstash-Message-Id": "msg_1"})
    assert alerter.sent == [("worker_heartbeat", {"message_id": "msg_1"})]


# --- Failure callback (job exhausted its retries, now in the DLQ) -----------


def test_failure_callback_alerts_with_ids_only(client, alerter) -> None:
    callback = {
        "status": 500,
        "header": {"Content-Type": ["application/json"]},
        "body": "eyJkZXRhaWwiOiJKb2IgZmFpbGVkIn0=",
        "retried": 2,
        "maxRetries": 2,
        "dlqId": "1725323658779-0",
        "sourceMessageId": "msg_abc",
        "url": f"{BASE}/jobs/debug.fail",
        "method": "POST",
        # The original job payload: must never reach the alert.
        "sourceBody": "eyJlbWFpbCI6ImRhbmFAZXhhbXBsZS5jb20ifQ==",
        "scheduleId": None,
    }
    response = post_signed(client, "/qstash/failure", json.dumps(callback).encode())
    assert response.status_code == 200
    assert alerter.sent == [
        (
            "job_failed",
            {
                "job": "debug.fail",
                "message_id": "msg_abc",
                "dlq_id": "1725323658779-0",
                "status": 500,
                "retried": 2,
                "max_retries": 2,
                "schedule_id": None,
            },
        )
    ]


def test_failure_callback_requires_signature(client, alerter) -> None:
    assert client.post("/qstash/failure", content=b"{}").status_code == 401
    assert alerter.sent == []


# --- Registry and schedules -------------------------------------------------


def test_job_names_validated() -> None:
    with pytest.raises(ValueError):
        jobs.job("NoDots")


def test_resolve() -> None:
    assert resolve("debug.fail", "staging") is REGISTRY["debug.fail"]
    assert resolve("debug.fail", "prod") is None
    assert resolve("missing.job", "staging") is None


def test_every_schedule_targets_a_registered_non_debug_job() -> None:
    for schedule in SCHEDULES:
        assert schedule.id.startswith(jobs.SCHEDULE_PREFIX)
        spec = REGISTRY[schedule.job]
        assert not spec.debug_only


async def test_sync_schedules_upserts_and_removes_stale(alerter) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"scheduleId": "bool-system-heartbeat"},
                    {"scheduleId": "bool-old-job"},
                    {"scheduleId": "someone-elses"},
                ],
            )
        if request.method == "POST":
            return httpx.Response(200, json={"scheduleId": request.headers["upstash-schedule-id"]})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await sync_schedules(QStashClient("https://q.example", "tok", http), BASE, 3, alerter)

    assert ("POST", f"/v2/schedules/{BASE}/jobs/system.heartbeat") in calls
    assert ("DELETE", "/v2/schedules/bool-old-job") in calls
    assert ("DELETE", "/v2/schedules/someone-elses") not in calls
    assert alerter.sent == []


async def test_sync_failure_alerts(alerter) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        await sync_schedules(QStashClient("https://q.example", "tok", http), BASE, 3, alerter)
    assert alerter.sent == [("schedule_sync_failed", {})]
