"""Canonical request-bound opaque-session dependencies for control routers."""

import hmac
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal

SESSION_COOKIE = "__Host-animetron_session"


def auth_dependencies(
    config: AuthConfig | None, store: AuthStore | None,
) -> tuple[Callable[[Request], Principal], Callable[..., Principal]]:
    """Create shared fresh-session and owner dependencies for API routers."""

    def principal(request: Request) -> Principal:
        if config is None or store is None:
            raise AuthDenied("AUTH_UNAVAILABLE", 503)
        if (
            str(request.url).split("/api/v1", 1)[0] != config.origin
            or request.headers.get("origin", config.origin) != config.origin
            or len(request.headers.getlist("origin")) > 1
        ):
            store.audit("access_denied", request.state.request_id)
            raise AuthDenied("ORIGIN_REJECTED", 403)
        try:
            user = store.authenticate(request.cookies.get(SESSION_COOKIE, ""))
            if request.method not in ("GET", "HEAD", "OPTIONS") and (
                request.headers.get("origin") != config.origin
                or len(request.headers.getlist("x-csrf-token")) != 1
                or not hmac.compare_digest(
                    request.headers.get("x-csrf-token", "").encode(),
                    user.csrf.encode(),
                )
            ):
                raise AuthDenied("CSRF_REJECTED", 403)
            return user
        except AuthDenied:
            store.audit("access_denied", request.state.request_id)
            raise

    def owner(
        request: Request, user: Annotated[Principal, Depends(principal)],
    ) -> Principal:
        if user.role != "owner":
            if store is None:
                raise AuthDenied("AUTH_UNAVAILABLE", 503)
            store.audit("access_denied", request.state.request_id, user.id)
            raise AuthDenied("FORBIDDEN", 403)
        return user

    return principal, owner
