import asyncio
import hmac
import secrets
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx2 as httpx
from fastapi import APIRouter, Depends, Query, Request, WebSocket
from joserfc.errors import JoseError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.websockets import WebSocketDisconnect

from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal, request_id
from app.core.oidc import Keycloak, OAuthError

SESSION_COOKIE = "__Host-animetron_session"
LOGIN_COOKIE = "__Host-animetron_login"


class SessionResponse(BaseModel):
    principal_id: str = Field(alias="principalId")
    role: Literal["owner", "operator", "viewer"]
    csrf_token: str = Field(alias="csrfToken")
    expires_at: datetime = Field(alias="expiresAt")


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    database: Literal["ready"] = "ready"
    identity_provider: Literal["ready"] = Field(default="ready", alias="identityProvider")


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: int
    event: str
    principal_id: str | None = Field(alias="principalId")
    request_id: str = Field(alias="requestId")
    occurred_at: datetime = Field(alias="occurredAt")


class AuditPageResponse(BaseModel):
    data: list[AuditEventResponse]
    next_cursor: int | None = Field(alias="nextCursor")


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str = Field(alias="requestId")


class ErrorResponse(BaseModel):
    error: ErrorDetail


def auth_router(config: AuthConfig | None, store: AuthStore | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses={
        status: {"model": ErrorResponse}
        for status in (400, 401, 403, 422, 429, 503)
    })
    provider = Keycloak(config) if config else None

    def available() -> tuple[AuthConfig, AuthStore, Keycloak]:
        if config is None or store is None or provider is None:
            raise AuthDenied("AUTH_UNAVAILABLE", 503)
        return config, store, provider

    def boundary(request: Request) -> tuple[AuthConfig, AuthStore, Keycloak]:
        settings, persistence, oidc = available()
        if (
            str(request.url).split("/api/v1", 1)[0] != settings.origin
            or request.headers.get("origin", settings.origin) != settings.origin
            or len(request.headers.getlist("origin")) > 1
        ):
            persistence.audit("access_denied", request.state.request_id)
            raise AuthDenied("ORIGIN_REJECTED", 403)
        return settings, persistence, oidc

    def principal(request: Request) -> Principal:
        settings, persistence, _ = boundary(request)
        try:
            user = persistence.authenticate(request.cookies.get(SESSION_COOKIE, ""))
            if request.method not in ("GET", "HEAD", "OPTIONS") and (
                request.headers.get("origin") != settings.origin
                or len(request.headers.getlist("x-csrf-token")) != 1
                or not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), user.csrf.encode())
            ):
                raise AuthDenied("CSRF_REJECTED", 403)
            return user
        except AuthDenied:
            persistence.audit("access_denied", request.state.request_id)
            raise

    def owner(request: Request, user: Annotated[Principal, Depends(principal)]) -> Principal:
        if user.role != "owner":
            available()[1].audit("access_denied", request.state.request_id, user.id)
            raise AuthDenied("FORBIDDEN", 403)
        return user

    @router.get("/auth/login", status_code=302, response_class=RedirectResponse)
    async def login(request: Request) -> RedirectResponse:
        _, persistence, oidc = boundary(request)
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 400)
        nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        state, browser = await run_in_threadpool(
            persistence.start_login, nonce, verifier, request.state.request_id,
        )
        try:
            url = await oidc.authorize(state, nonce, verifier)
        except (httpx.HTTPError, TimeoutError, ValueError):
            raise AuthDenied("PROVIDER_UNAVAILABLE", 503) from None
        response = RedirectResponse(url, status_code=302)
        response.set_cookie(LOGIN_COOKIE, browser, max_age=300, secure=True,
                            httponly=True, samesite="lax", path="/")
        return response

    @router.get("/auth/callback", status_code=303, response_class=RedirectResponse)
    async def callback(request: Request) -> RedirectResponse:
        settings, persistence, oidc = boundary(request)
        try:
            if (
                len(request.scope.get("query_string", b"")) > 8192
                or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params)
                or set(request.query_params) - {"state", "code", "iss", "session_state", "error", "error_description"}
            ):
                raise AuthDenied("INVALID_REQUEST", 400)
            challenge = await run_in_threadpool(
                persistence.consume_login, request.query_params.get("state", ""),
                request.cookies.get(LOGIN_COOKIE, ""),
            )
            code = request.query_params.get("code", "")
            if (
                request.query_params.get("error") or not code or len(code) > 2048
                or request.query_params.get("iss", settings.issuer) != settings.issuer
            ):
                raise AuthDenied("IDENTITY_REJECTED", 400)
            try:
                subject = await oidc.identity(code, str(challenge["nonce"]), str(challenge["verifier"]))
            except (httpx.HTTPError, TimeoutError):
                raise AuthDenied("PROVIDER_UNAVAILABLE", 503) from None
            except AuthDenied:
                raise
            except (OAuthError, JoseError, ValueError, TypeError, KeyError, RuntimeError):
                # OAuth/JOSE errors can carry tokens or attacker descriptions.
                raise AuthDenied("IDENTITY_REJECTED", 400) from None
            handle, _ = await run_in_threadpool(
                persistence.create_session, subject, request.state.request_id,
            )
        except AuthDenied:
            await run_in_threadpool(persistence.audit, "login_failed", request.state.request_id)
            raise
        response = RedirectResponse(settings.origin + "/api/v1/auth/session", status_code=303)
        response.delete_cookie(LOGIN_COOKIE, secure=True, httponly=True, samesite="lax")
        response.set_cookie(SESSION_COOKIE, handle, max_age=settings.session_seconds,
                            secure=True, httponly=True, samesite="lax", path="/")
        return response

    @router.get("/auth/session")
    def current_session(user: Annotated[Principal, Depends(principal)]) -> SessionResponse:
        return SessionResponse(principalId=user.id, role=user.role,
                               csrfToken=user.csrf, expiresAt=user.expires_at)

    @router.post("/auth/logout", status_code=303, response_class=RedirectResponse)
    async def logout(request: Request, user: Annotated[Principal, Depends(principal)]) -> RedirectResponse:
        _, persistence, oidc = available()
        await run_in_threadpool(persistence.revoke, request.cookies[SESSION_COOKIE], request.state.request_id)
        response = RedirectResponse(await oidc.logout_url(), status_code=303)
        response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax")
        response.delete_cookie(LOGIN_COOKIE, secure=True, httponly=True, samesite="lax")
        return response

    @router.get("/readiness")
    async def readiness(
        request: Request, user: Annotated[Principal, Depends(principal)],
    ) -> ReadinessResponse:
        _, persistence, oidc = available()
        if user.role not in ("owner", "operator"):
            await run_in_threadpool(persistence.audit, "access_denied", request.state.request_id, user.id)
            raise AuthDenied("FORBIDDEN", 403)
        try:
            async with asyncio.timeout(10):
                await oidc.client(with_keys=True)
        except (httpx.HTTPError, TimeoutError, ValueError):
            raise AuthDenied("PROVIDER_UNAVAILABLE", 503) from None
        # Dependency performed real session persistence queries before this point.
        # No inference/artifact/deployment readiness is implied.
        return ReadinessResponse()

    @router.get("/audit-events")
    def audit_history(
        user: Annotated[Principal, Depends(owner)],
        cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> AuditPageResponse:
        rows = available()[1].audit_page(cursor, limit + 1)
        return AuditPageResponse(
            data=[AuditEventResponse.model_validate(row) for row in rows[:limit]],
            nextCursor=int(str(rows[limit - 1]["id"])) if len(rows) > limit else None,
        )

    @router.websocket("/ws")
    async def websocket_handshake(websocket: WebSocket) -> None:
        correlation = request_id()
        persistence: AuthStore | None = None
        try:
            settings, persistence, _ = available()
            target = urlsplit(str(websocket.url))
            if (
                websocket.headers.get("origin") != settings.origin
                or len(websocket.headers.getlist("origin")) != 1
                or "https://" + target.netloc != settings.origin or target.scheme != "wss"
                or websocket.query_params
            ):
                raise AuthDenied("ORIGIN_REJECTED", 403)
            handle = websocket.cookies.get(SESSION_COOKIE, "")
            user = await run_in_threadpool(persistence.authenticate, handle, touch=False)
            await run_in_threadpool(persistence.audit, "websocket_authenticated", correlation, user.id)
            await websocket.accept()
            await websocket.send_json({"type": "authenticated", "principalId": user.id})
            # Handshake/heartbeat only: not workflow events. Revalidate on every
            # frame and at least every 15s so logout/expiry closes open sockets.
            while True:
                user = await run_in_threadpool(persistence.authenticate, handle, touch=False)
                try:
                    async with asyncio.timeout(15):
                        message = await websocket.receive()
                except TimeoutError:
                    continue
                if message["type"] == "websocket.disconnect":
                    return
                user = await run_in_threadpool(persistence.authenticate, handle)
                if message.get("text") != "ping":
                    await websocket.close(code=1008)
                    return
                await websocket.send_json({"type": "pong"})
        except AuthDenied as error:
            if persistence:
                await run_in_threadpool(persistence.audit, "access_denied", correlation)
            await websocket.close(code=4401 if error.status == 401 else 4403)
        except WebSocketDisconnect:
            return
        except (SQLAlchemyError, OSError, RuntimeError, ValueError):
            await websocket.close(code=1011)

    return router
