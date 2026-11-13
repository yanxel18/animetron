import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import SecurityHeaders, app


def test_health_reports_liveness_only() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/api/v1/health", "/not-found"])
def test_http_responses_have_browser_security_headers(path: str) -> None:
    with TestClient(app) as client:
        response = client.get(path)

    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_unhandled_error_response_has_browser_security_headers() -> None:
    api = FastAPI()

    @api.get("/error")
    async def fail() -> None:
        raise RuntimeError("internal detail")

    with TestClient(SecurityHeaders(api), raise_server_exceptions=False) as client:
        response = client.get("/error")

    assert response.status_code == 500
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
