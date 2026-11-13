"""Real isolated Keycloak authorization-code flow, never enabled by inherited URLs."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from owned_auth_database import reset_auth_tables
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.core.auth import (
    AuthConfig,
    AuthDenied,
    AuthStore,
    audit_events,
    sessions,
)
from app.core.database import create_database_engine
from app.main import SecurityHeaders, create_api


class ProviderBrowser:
    """Never let the provider's redirect transmit a code to an external host."""

    def __init__(self, context, config):
        self.page = context.new_page()
        self.config = config
        self.callback = None
        context.route("**/*", self.isolated_network)

    def isolated_network(self, route):
        target = urlsplit(route.request.url)
        if target.netloc != urlsplit(self.config.issuer).netloc or target.scheme != "http":
            route.abort()
            return
        # Intercept before Chromium follows a 302: Playwright does not reroute
        # every redirected URL when the original route uses continue_().
        response = route.fetch(max_redirects=0)
        destination = response.headers.get("location", "")
        if destination.startswith(self.config.callback_uri + "?"):
            self.callback = destination
            route.fulfill(status=200, content_type="text/plain", body="Isolated callback")
        else:
            route.fulfill(response=response)

    def goto(self, url):
        try:
            return self.page.goto(url)
        except BrowserError:
            pytest.fail("Isolated browser navigation failed", pytrace=False)

    def authorize(self, url):
        self.callback = None
        self.goto(url)
        if self.callback is None:
            try:
                self.page.locator("#username").fill("test-owner")
                self.page.locator("#password").fill(os.environ["ANIMETRON_TEST_OIDC_PASSWORD"])
                self.page.locator("#kc-login").click()
            except BrowserError:
                pytest.fail("Isolated provider credential submission failed", pytrace=False)
        if self.callback is None:
            pytest.fail("Provider did not return the exact isolated callback", pytrace=False)
        return self.callback


@pytest.fixture
def live_context():
    if not os.environ.get("ANIMETRON_TEST_OIDC_ISSUER"):
        pytest.fail("Use tests/run_auth_checks.py for the isolated real provider flow")
    config = AuthConfig(
        issuer=os.environ["ANIMETRON_TEST_OIDC_ISSUER"],
        client_id="animetron", client_secret=os.environ["ANIMETRON_TEST_OIDC_CLIENT_SECRET"],
        origin="https://control.example",
        owner_subject=os.environ["ANIMETRON_TEST_OIDC_OWNER"],
        allow_loopback_provider_http=True,
    )
    engine = create_database_engine(os.environ["ANIMETRON_TEST_DATABASE_URL"])
    store = AuthStore(engine, config)
    reset_auth_tables(engine)
    with (
        TestClient(SecurityHeaders(create_api(config, engine)), base_url=config.origin) as client,
        sync_playwright() as playwright,
    ):
        # Keycloak treats loopback HTTP as a secure context and sets Secure
        # cookies. A real browser honours that; Python CookieJar does not.
        # Existing Edge is read-only: no browser or OS installation is performed.
        browser = playwright.chromium.launch(channel="msedge", headless=True, args=[
            "--disable-background-networking", "--disable-component-update",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
        ])
        context = browser.new_context(service_workers="block")
        provider_browser = ProviderBrowser(context, config)
        try:
            yield config, engine, store, client, provider_browser
        except BrowserError:
            pytest.fail("Isolated browser provider flow failed", pytrace=False)
        finally:
            context.close()
            browser.close()
    engine.dispose()


def authorization_callback(client, browser, config):
    login = client.get("/api/v1/auth/login", follow_redirects=False)
    assert login.status_code == 302
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    authorization_url = login.headers["location"]
    query = parse_qs(urlsplit(authorization_url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [config.callback_uri]
    assert query["nonce"] and query["state"]
    return browser.authorize(authorization_url)


def test_real_login_readiness_restart_rotation_and_logout(live_context):
    config, engine, store, client, browser = live_context
    callback = authorization_callback(client, browser, config)
    response = client.get(callback, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == config.origin + "/api/v1/auth/session"
    cookie = response.headers.get_list("set-cookie")[-1]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    handle = client.cookies.get("__Host-animetron_session")
    assert len(handle) == 43 and "." not in handle
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200 and session.json()["role"] == "owner"
    assert client.get("/api/v1/readiness").json() == {
        "status": "ready", "database": "ready", "identityProvider": "ready",
    }
    assert client.get("/api/v1/auth/login?redirect=https://evil.example").status_code == 400
    assert client.get(callback, follow_redirects=False).status_code == 400
    second_engine = create_database_engine(os.environ["ANIMETRON_TEST_DATABASE_URL"])
    try:
        with TestClient(SecurityHeaders(create_api(config, second_engine)),
                        base_url=config.origin) as restarted:
            restarted.cookies.set("__Host-animetron_session", handle)
            assert restarted.get("/api/v1/auth/session").status_code == 200
            new_login = restarted.get("/api/v1/auth/login", follow_redirects=False)
            # Provider already has a browser SSO cookie: real authorization redirect.
            new_callback = browser.authorize(new_login.headers["location"])
            assert restarted.get(new_callback, follow_redirects=False).status_code == 303
            with pytest.raises(AuthDenied):
                store.authenticate(handle)
            info = restarted.get("/api/v1/auth/session").json()
            logout = restarted.post("/api/v1/auth/logout", follow_redirects=False, headers={
                "Origin": config.origin, "X-CSRF-Token": info["csrfToken"],
            })
            assert logout.status_code == 303
            assert logout.headers["location"].startswith(
                config.issuer + "/protocol/openid-connect/logout?"
            )
            assert restarted.get("/api/v1/auth/session").status_code == 401
            # Standard provider confirmation (no ID token retained by our backend).
            browser.goto(logout.headers["location"])
            assert browser.page.locator("#kc-logout").is_visible()
            browser.page.locator("#kc-logout").click()
            # Real provider logout is proven by a subsequent authorization
            # requiring credentials again, not merely by a local 303.
            login_after_logout = restarted.get("/api/v1/auth/login", follow_redirects=False)
            browser.goto(login_after_logout.headers["location"])
            assert browser.page.locator("#username").is_visible()
    finally:
        second_engine.dispose()
    with engine.connect() as conn:
        rows = conn.execute(select(audit_events)).mappings().all()
    assert any(row["event"] == "logout" for row in rows)
    assert all(handle not in str(row) and config.client_secret not in str(row) for row in rows)


def test_real_unlisted_subject_cannot_become_owner(live_context):
    config, engine, _, _, browser = live_context
    restricted = replace(config, owner_subject="not-the-provider-user")
    with TestClient(SecurityHeaders(create_api(restricted, engine)),
                    base_url=restricted.origin) as client:
        callback = authorization_callback(client, browser, restricted)
        assert client.get(callback, follow_redirects=False).status_code == 403
        assert client.get("/api/v1/auth/session").status_code == 401


def test_real_concurrent_callbacks_have_exactly_one_winner(live_context):
    config, engine, _, client, browser = live_context
    callback = authorization_callback(client, browser, config)
    binding = client.cookies.get("__Host-animetron_login")

    def complete(_):
        with TestClient(SecurityHeaders(create_api(config, engine)),
                        base_url=config.origin) as contender:
            contender.cookies.set("__Host-animetron_login", binding)
            return contender.get(callback, follow_redirects=False).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(complete, range(2))) == [303, 400]
    with engine.connect() as conn:
        assert len(conn.execute(select(sessions)).all()) == 1
