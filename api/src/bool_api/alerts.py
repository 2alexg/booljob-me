"""Admin alerts via a Telegram bot.

Alerts carry IDs only, never personal data. Every field value must be an
int, bool, UUID, or a short token of [A-Za-z0-9_.:-]; anything else (emails,
phone numbers, names, free text, Hebrew) is replaced with "[redacted]"
before sending.
"""

import logging
import re
from typing import Protocol
from uuid import UUID

import httpx

from bool_api.config import Settings

log = logging.getLogger(__name__)

REDACTED = "[redacted]"
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def _safe_value(value: object) -> str:
    if isinstance(value, bool | int | UUID):
        return str(value)
    if isinstance(value, str) and _SAFE_TOKEN.match(value):
        return value
    return REDACTED


def format_alert(event: str, environment: str, fields: dict[str, object]) -> str:
    if not _SAFE_TOKEN.match(event):
        raise ValueError(f"alert event name must be a short token, got {event!r}")
    lines = [f"[{environment}] {event}"]
    for key, value in fields.items():
        if value is None:
            continue
        if not _SAFE_KEY.match(key):
            raise ValueError(f"alert field name must be snake_case, got {key!r}")
        lines.append(f"{key}: {_safe_value(value)}")
    return "\n".join(lines)


class Alerter(Protocol):
    async def send(self, event: str, **fields: object) -> None: ...


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str, environment: str, http: httpx.AsyncClient) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._environment = environment
        self._http = http

    async def send(self, event: str, **fields: object) -> None:
        text = format_alert(event, self._environment, fields)
        response = await self._http.post(
            self._url,
            json={"chat_id": self._chat_id, "text": text, "disable_web_page_preview": True},
        )
        if response.status_code != 200:
            # Never log the URL: it contains the bot token.
            raise RuntimeError(f"Telegram sendMessage failed with HTTP {response.status_code}")


class LogAlerter:
    """Used when Telegram is not configured (local, tests)."""

    def __init__(self, environment: str) -> None:
        self._environment = environment

    async def send(self, event: str, **fields: object) -> None:
        log.warning(
            "alert (telegram not configured): %s", format_alert(event, self._environment, fields)
        )


def build_alerter(settings: Settings, http: httpx.AsyncClient) -> Alerter:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramAlerter(
            settings.telegram_bot_token.get_secret_value(),
            settings.telegram_chat_id,
            settings.environment,
            http,
        )
    return LogAlerter(settings.environment)
