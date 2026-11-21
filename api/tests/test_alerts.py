import json
from uuid import UUID

import httpx
import pytest

from bool_api.alerts import REDACTED, LogAlerter, TelegramAlerter, build_alerter, format_alert
from bool_api.config import Settings


def test_ids_pass_through() -> None:
    text = format_alert(
        "job_failed",
        "staging",
        {
            "job": "debug.fail",
            "message_id": "msg_2KxaQ9-abc",
            "candidate_id": UUID("11111111-1111-1111-1111-111111111111"),
            "retried": 2,
            "ok": False,
            "skipped": None,
        },
    )
    assert text == (
        "[staging] job_failed\n"
        "job: debug.fail\n"
        "message_id: msg_2KxaQ9-abc\n"
        "candidate_id: 11111111-1111-1111-1111-111111111111\n"
        "retried: 2\n"
        "ok: False"
    )


@pytest.mark.parametrize(
    "value",
    [
        "dana.cohen@example.com",
        "+972501234567",
        "Dana Cohen",
        "דנה כהן",
        "free text with spaces",
        "x" * 81,
        {"nested": "dict"},
        ["list"],
        3.14,
    ],
)
def test_personal_data_is_redacted(value) -> None:
    assert format_alert("evt", "staging", {"field": value}).endswith(f"field: {REDACTED}")


@pytest.mark.parametrize("event", ["has space", "dana@example.com", ""])
def test_event_name_must_be_a_token(event) -> None:
    with pytest.raises(ValueError):
        format_alert(event, "staging", {})


def test_field_names_must_be_snake_case() -> None:
    with pytest.raises(ValueError):
        format_alert("evt", "staging", {"Bad Key": 1})


async def test_telegram_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await TelegramAlerter("123:ABC", "-100777", "staging", http).send("job_failed", job="x.y")
    (req,) = seen
    assert str(req.url) == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert json.loads(req.content) == {
        "chat_id": "-100777",
        "text": "[staging] job_failed\njob: x.y",
        "disable_web_page_preview": True,
    }


async def test_telegram_error_does_not_leak_token() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(403, json={"ok": False}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(RuntimeError) as exc:
            await TelegramAlerter("123:SECRET", "1", "staging", http).send("evt")
    assert "SECRET" not in str(exc.value)


async def test_build_alerter() -> None:
    async with httpx.AsyncClient() as http:
        assert isinstance(build_alerter(Settings(), http), LogAlerter)
        configured = Settings(telegram_bot_token="1:x", telegram_chat_id="2")
        assert isinstance(build_alerter(configured, http), TelegramAlerter)
