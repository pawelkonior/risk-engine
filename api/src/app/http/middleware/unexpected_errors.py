from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request

from app.http.exception_handlers import handle_unexpected_error

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UnexpectedErrorsMiddleware:
    """Keep safe failures inside CORS, access logging, and request context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track_start(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_start)
        except Exception as error:
            if started:
                raise
            response = await handle_unexpected_error(Request(scope), error)
            await response(scope, receive, send)
