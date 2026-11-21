"""Zero-trust gateway: reject any request without the BFF's X-Internal-Secret (403)."""

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = b"x-internal-secret"


class InternalSecretMiddleware:
    def __init__(self, app: ASGIApp, secret: str, exempt_paths: frozenset[str]) -> None:
        self.app = app
        self._secret = secret.encode()
        self._exempt = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self._exempt:
            await self.app(scope, receive, send)
            return

        provided = next((v for k, v in scope["headers"] if k == HEADER), None)
        if provided is None or not hmac.compare_digest(provided, self._secret):
            response = JSONResponse({"detail": "Forbidden"}, status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
