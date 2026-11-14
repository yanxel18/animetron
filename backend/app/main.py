import json
import os
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.auth import auth_router
from app.api.reviews import reviews_router
from app.api.runs import runs_router
from app.api.schedules import schedules_router
from app.core.auth import AuthConfig, AuthDenied, AuthStore, request_id
from app.core.database import create_database_engine


class SecurityHeaders:
    def __init__(self, application: ASGIApp) -> None:
        self.application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        correlation = request_id()
        scope.setdefault("state", {})["request_id"] = correlation

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = (
                    "default-src 'none'; frame-ancestors 'none'"
                )
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Request-ID"] = correlation
                headers["Cache-Control"] = "no-store"
                if scope.get("scheme") == "https":
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        await self.application(scope, receive, send_with_headers)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


async def health() -> HealthResponse:
    return HealthResponse()


def create_api(config: AuthConfig | None = None, engine: Engine | None = None) -> FastAPI:
    api = FastAPI(title="AnimeTron API", docs_url=None, redoc_url=None, openapi_url=None)
    api.add_api_route("/api/v1/health", health, methods=["GET"])
    store = AuthStore(engine, config) if engine is not None and config is not None else None
    api.include_router(auth_router(config, store))
    api.include_router(runs_router(config, store))
    api.include_router(reviews_router(config, store))
    api.include_router(schedules_router(config, store))

    def failure(request: Request, status: int, code: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": "Request could not be completed",
            "requestId": request.state.request_id,
        }})

    @api.exception_handler(AuthDenied)
    async def auth_error(request: Request, error: AuthDenied) -> JSONResponse:
        return failure(request, error.status, error.code)

    @api.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return failure(request, error.status_code, "HTTP_ERROR")

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return failure(request, 422, "INVALID_REQUEST")

    @api.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        return failure(request, 503, "DEPENDENCY_UNAVAILABLE")

    return api


def configured_api() -> FastAPI:
    try:
        config = AuthConfig(
            issuer=os.environ["ANIMETRON_OIDC_ISSUER"],
            client_id=os.environ["ANIMETRON_OIDC_CLIENT_ID"],
            client_secret=os.environ["ANIMETRON_OIDC_CLIENT_SECRET"],
            origin=os.environ["ANIMETRON_BROWSER_ORIGIN"],
            owner_subject=os.environ["ANIMETRON_OWNER_SUBJECT"],
            grants=json.loads(os.environ.get("ANIMETRON_SUBJECT_GRANTS", "{}")),
        )
        url = make_url(os.environ["ANIMETRON_DATABASE_URL"]).update_query_dict({
            "connect_timeout": "5", "options": "-c statement_timeout=3000 -c lock_timeout=3000",
        })
        engine = create_database_engine(url.render_as_string(hide_password=False))
    except (KeyError, ValueError, TypeError, AttributeError, ArgumentError):
        # Partial configuration is disabled, never a fabricated principal.
        return create_api()
    return create_api(config, engine)


api = configured_api()
app = SecurityHeaders(api)
