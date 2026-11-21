"""Upstash QStash: publishing jobs, managing schedules, verifying deliveries.

QStash signs every delivery (jobs and failure callbacks) with a JWT in the
Upstash-Signature header: HS256 with the current or next signing key,
issuer "Upstash", `sub` = the destination URL, and `body` = base64url of the
SHA-256 of the raw request body.
"""

import base64
import hashlib
import hmac
import json
from typing import Any

import httpx
import jwt


class QStashSignatureError(Exception):
    pass


class SignatureVerifier:
    def __init__(self, current_key: str, next_key: str, leeway_seconds: int = 5) -> None:
        self._keys = (current_key, next_key)
        self._leeway = leeway_seconds

    def verify(self, signature: str | None, body: bytes, url: str) -> None:
        if not signature:
            raise QStashSignatureError("missing Upstash-Signature header")
        for key in self._keys:
            try:
                claims = jwt.decode(
                    signature,
                    key,
                    algorithms=["HS256"],
                    issuer="Upstash",
                    leeway=self._leeway,
                    options={"require": ["iss", "sub", "exp", "nbf", "body"]},
                )
            except jwt.InvalidSignatureError:
                continue  # try the other key (keys rotate)
            except jwt.PyJWTError as e:
                raise QStashSignatureError(f"invalid signature: {e}") from e

            if claims["sub"] != url:
                raise QStashSignatureError("signature was issued for a different URL")
            expected = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode()
            if not hmac.compare_digest(claims["body"].rstrip("="), expected.rstrip("=")):
                raise QStashSignatureError("body does not match the signature")
            return
        raise QStashSignatureError("signature does not match either signing key")


class QStashClient:
    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._http = http

    def _headers(self, retries: int, failure_callback: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Upstash-Retries": str(retries),
        }
        if failure_callback:
            headers["Upstash-Failure-Callback"] = failure_callback
        return headers

    async def publish(
        self,
        destination: str,
        payload: dict[str, Any],
        *,
        retries: int,
        failure_callback: str | None,
        deduplication_id: str | None = None,
        delay_seconds: int | None = None,
    ) -> str:
        headers = self._headers(retries, failure_callback)
        if deduplication_id:
            headers["Upstash-Deduplication-Id"] = deduplication_id
        if delay_seconds:
            headers["Upstash-Delay"] = f"{delay_seconds}s"
        response = await self._http.post(
            f"{self._base}/v2/publish/{destination}", content=json.dumps(payload), headers=headers
        )
        response.raise_for_status()
        return str(response.json()["messageId"])

    async def upsert_schedule(
        self,
        schedule_id: str,
        destination: str,
        cron: str,
        *,
        retries: int,
        failure_callback: str | None,
    ) -> str:
        headers = self._headers(retries, failure_callback)
        headers["Upstash-Cron"] = cron
        # A fixed id makes this an upsert: re-running updates the same schedule.
        headers["Upstash-Schedule-Id"] = schedule_id
        response = await self._http.post(
            f"{self._base}/v2/schedules/{destination}", content="{}", headers=headers
        )
        response.raise_for_status()
        return str(response.json()["scheduleId"])

    async def list_schedules(self) -> list[dict[str, Any]]:
        response = await self._http.get(
            f"{self._base}/v2/schedules", headers={"Authorization": f"Bearer {self._token}"}
        )
        response.raise_for_status()
        return list(response.json())

    async def delete_schedule(self, schedule_id: str) -> None:
        response = await self._http.delete(
            f"{self._base}/v2/schedules/{schedule_id}",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        response.raise_for_status()
