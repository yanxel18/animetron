"""Keycloak authorization-code integration, using Authlib's maintained OIDC client."""

import asyncio
import logging
from collections.abc import Mapping
from importlib import import_module
from typing import Protocol, cast

import httpx2 as httpx

from app.core.auth import AuthConfig, AuthDenied

OAuthError = cast(type[Exception], import_module("authlib.integrations.base_client").OAuthError)

# Authlib's PKCE helper emits the verifier at DEBUG. It must never reach logs.
logging.getLogger("authlib.integrations.base_client.sync_app").disabled = True


class OidcClient(Protocol):
    """Narrow typed boundary for Authlib's documented, currently untyped API."""

    async def create_authorization_url(
        self, redirect_uri: str, **kwargs: object,
    ) -> Mapping[str, str]: ...

    async def fetch_access_token(
        self, redirect_uri: str, **kwargs: object,
    ) -> Mapping[str, object]: ...

    async def parse_id_token(
        self, token: Mapping[str, object], nonce: str, **kwargs: object,
    ) -> Mapping[str, object] | None: ...

    async def create_logout_url(self, **kwargs: object) -> Mapping[str, str]: ...


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, allowed_urls: set[str]) -> None:
        self.allowed_urls = allowed_urls
        self.transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) not in self.allowed_urls:
            raise AuthDenied("PROVIDER_UNAVAILABLE", 503)
        response = await self.transport.handle_async_request(request)
        try:
            if response.headers.get("content-encoding", "identity") != "identity":
                raise AuthDenied("PROVIDER_UNAVAILABLE", 503)
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > 262144:
                    raise AuthDenied("PROVIDER_UNAVAILABLE", 503)
                content.extend(chunk)
            return httpx.Response(response.status_code, headers=response.headers,
                                  content=bytes(content), request=request)
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        await self.transport.aclose()


class Keycloak:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self.discovery_url = config.issuer + "/.well-known/openid-configuration"
        base = config.issuer + "/protocol/openid-connect/"
        self.endpoints = {
            "authorization_endpoint": base + "auth",
            "token_endpoint": base + "token",
            "jwks_uri": base + "certs",
            "end_session_endpoint": base + "logout",
        }
        self.allowed_urls = {self.discovery_url, *self.endpoints.values()}

    async def get_json(self, url: str) -> Mapping[str, object]:
        async with httpx.AsyncClient(
            timeout=5, trust_env=False, follow_redirects=False,
            transport=BoundedTransport(self.allowed_urls),
            headers={"Accept-Encoding": "identity"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise AuthDenied("PROVIDER_UNAVAILABLE", 503)
            return cast(Mapping[str, object], data)

    async def client(self, *, with_keys: bool = False) -> OidcClient:
        metadata = await self.get_json(self.discovery_url)
        if metadata.get("issuer") != self.config.issuer or any(
            metadata.get(key) != value for key, value in self.endpoints.items()
        ):
            raise AuthDenied("PROVIDER_UNAVAILABLE", 503)
        for key, required in (
            ("code_challenge_methods_supported", "S256"),
            ("id_token_signing_alg_values_supported", "RS256"),
            ("response_types_supported", "code"),
            ("token_endpoint_auth_methods_supported", "client_secret_basic"),
        ):
            values = metadata.get(key)
            if not isinstance(values, list) or required not in values:
                raise AuthDenied("PROVIDER_UNAVAILABLE", 503)
        trusted: dict[str, object] = {
            "issuer": self.config.issuer,
            "authorization_endpoint": self.endpoints["authorization_endpoint"],
            "token_endpoint": self.endpoints["token_endpoint"],
            "end_session_endpoint": self.endpoints["end_session_endpoint"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        if with_keys:
            # Fetch freshly for each callback. No unbounded library JWKS retry:
            # omit jwks_uri; a missing key fails closed until the next login.
            keys = await self.get_json(self.endpoints["jwks_uri"])
            key_list = keys.get("keys")
            if not isinstance(key_list, list) or not 1 <= len(key_list) <= 20:
                raise AuthDenied("PROVIDER_UNAVAILABLE", 503)
            trusted["jwks"] = dict(keys)
        # Public OAuth.register API:
        # https://docs.authlib.org/en/latest/oauth2/client/web/starlette.html
        oauth = import_module("authlib.integrations.starlette_client").OAuth()
        return cast(OidcClient, oauth.register(
            "keycloak", client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            client_kwargs={
                "scope": "openid", "code_challenge_method": "S256",
                "token_endpoint_auth_method": "client_secret_basic",
                "timeout": 5, "trust_env": False, "follow_redirects": False,
                "headers": {"Accept-Encoding": "identity"},
                "transport": BoundedTransport(self.allowed_urls),
            },
            **trusted,
        ))

    async def authorize(self, state: str, nonce: str, verifier: str) -> str:
        async with asyncio.timeout(10):
            client = await self.client()
            result = await client.create_authorization_url(
                self.config.callback_uri, state=state, nonce=nonce, code_verifier=verifier,
                response_mode="query",
            )
            return result["url"]

    async def identity(self, code: str, nonce: str, verifier: str) -> str:
        async with asyncio.timeout(15):
            client = await self.client(with_keys=True)
            token = await client.fetch_access_token(
                self.config.callback_uri, code=code, code_verifier=verifier,
                grant_type="authorization_code",
            )
            # Authlib verifies RS256 signature, exact issuer/audience, exp/iat,
            # nonce, azp (multi-audience), and at_hash when supplied.
            # https://docs.authlib.org/en/latest/oauth2/client/web/starlette.html#starlette-openid-connect
            claims = await client.parse_id_token(
                token, nonce=nonce, leeway=0, claims_options={
                    "iss": {"essential": True, "value": self.config.issuer},
                    "aud": {"essential": True, "value": self.config.client_id},
                },
            )
            if claims is None:
                raise AuthDenied("IDENTITY_REJECTED", 400)
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject or len(subject) > 255:
                raise AuthDenied("IDENTITY_REJECTED", 400)
            return subject

    async def logout_url(self) -> str:
        # Standard RP-initiated logout, without retaining any provider token.
        # Keycloak requests confirmation without id_token_hint. No arbitrary
        # post-logout redirect or local logout-completion claim is accepted.
        oauth = import_module("authlib.integrations.starlette_client").OAuth()
        client = cast(OidcClient, oauth.register(
            "keycloak", client_id=self.config.client_id,
            end_session_endpoint=self.endpoints["end_session_endpoint"],
        ))
        result = await client.create_logout_url(client_id=self.config.client_id)
        return result["url"]
