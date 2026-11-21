import base64
import hashlib
import json
import time

import httpx
import jwt
import pytest

from bool_api.qstash import QStashClient, QStashSignatureError, SignatureVerifier

CURRENT = "sig_current_key_for_tests_000000"
NEXT = "sig_next_key_for_tests_111111111"
URL = "https://worker.example/jobs/debug.ping"
BODY = b'{"hello":"world"}'


def sign(
    key: str = CURRENT,
    url: str = URL,
    body: bytes = BODY,
    *,
    iss: str = "Upstash",
    exp_in: int = 300,
    drop: str | None = None,
) -> str:
    now = int(time.time())
    claims = {
        "iss": iss,
        "sub": url,
        "exp": now + exp_in,
        "nbf": now - 1,
        "iat": now,
        "jti": "jwt_test",
        "body": base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode(),
    }
    if drop:
        claims.pop(drop)
    return jwt.encode(claims, key, algorithm="HS256")


@pytest.fixture
def verifier() -> SignatureVerifier:
    return SignatureVerifier(CURRENT, NEXT)


def test_valid_with_current_key(verifier) -> None:
    verifier.verify(sign(CURRENT), BODY, URL)


def test_valid_with_next_key(verifier) -> None:
    verifier.verify(sign(NEXT), BODY, URL)


def test_padding_in_body_hash_is_tolerated(verifier) -> None:
    verifier.verify(sign(), BODY, URL)  # urlsafe_b64encode keeps "=" padding


@pytest.mark.parametrize(
    ("token", "body", "url", "reason"),
    [
        (None, BODY, URL, "missing"),
        ("", BODY, URL, "missing"),
        (sign("sig_some_other_key_2222222222222"), BODY, URL, "either signing key"),
        (sign(), b'{"hello":"tampered"}', URL, "body does not match"),
        (sign(url="https://worker.example/jobs/debug.fail"), BODY, URL, "different URL"),
        (sign(exp_in=-60), BODY, URL, "expired"),
        (sign(iss="someone-else"), BODY, URL, "issuer"),
        (sign(drop="body"), BODY, URL, "body"),
        ("not-a-jwt", BODY, URL, "invalid signature"),
    ],
)
def test_rejections(verifier, token, body, url, reason) -> None:
    with pytest.raises(QStashSignatureError, match=reason):
        verifier.verify(token, body, url)


async def test_publish_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "msg_123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = QStashClient("https://qstash-eu-central-1.upstash.io/", "tok", http)
        message_id = await client.publish(
            URL,
            {"a": 1},
            retries=2,
            failure_callback="https://worker.example/qstash/failure",
            deduplication_id="dedup-1",
            delay_seconds=30,
        )
    assert message_id == "msg_123"
    (req,) = seen
    assert str(req.url) == f"https://qstash-eu-central-1.upstash.io/v2/publish/{URL}"
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["upstash-retries"] == "2"
    assert req.headers["upstash-failure-callback"] == "https://worker.example/qstash/failure"
    assert req.headers["upstash-deduplication-id"] == "dedup-1"
    assert req.headers["upstash-delay"] == "30s"
    assert json.loads(req.content) == {"a": 1}


async def test_upsert_schedule_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"scheduleId": "bool-x"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = QStashClient("https://q.example", "tok", http)
        assert (
            await client.upsert_schedule(
                "bool-x", URL, "CRON_TZ=Asia/Jerusalem 0 9 * * *", retries=3, failure_callback=None
            )
            == "bool-x"
        )
    (req,) = seen
    assert str(req.url) == f"https://q.example/v2/schedules/{URL}"
    assert req.headers["upstash-cron"] == "CRON_TZ=Asia/Jerusalem 0 9 * * *"
    assert req.headers["upstash-schedule-id"] == "bool-x"
    assert "upstash-failure-callback" not in req.headers


async def test_publish_raises_on_http_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad token"}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await QStashClient("https://q.example", "tok", http).publish(
                URL, {}, retries=0, failure_callback=None
            )
