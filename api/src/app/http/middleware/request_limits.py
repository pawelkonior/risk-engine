from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from app.core.config import HttpSettings
from app.core.context import get_request_id

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestLimitsMiddleware:
    """Buffer a bounded body before framework parsers can swallow limit errors."""

    def __init__(self, app: ASGIApp, *, settings: HttpSettings) -> None:
        self.app = app
        self._limit = settings.request_body_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self._content_length(scope) > self._limit:
            await self._reject(scope, receive, send)
            return

        chunks: list[bytes] = []
        consumed = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            consumed += len(chunk)
            if consumed > self._limit:
                await self._reject(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    def _content_length(scope: Scope) -> int:
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    return max(0, int(value))
                except ValueError:
                    return 0
        return 0

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": "Request body exceeds the accepted size",
                    "request_id": get_request_id(),
                    "details": {"max_bytes": self._limit},
                }
            },
        )
        await response(scope, receive, send)
