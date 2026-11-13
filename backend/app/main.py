from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

api = FastAPI(title="AnimeTron API", docs_url=None, redoc_url=None)


class SecurityHeaders:
    def __init__(self, application: ASGIApp) -> None:
        self.application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = (
                    "default-src 'none'; frame-ancestors 'none'"
                )
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)

        await self.application(scope, receive, send_with_headers)


app = SecurityHeaders(api)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@api.get("/api/v1/health")
async def health() -> HealthResponse:
    return HealthResponse()
