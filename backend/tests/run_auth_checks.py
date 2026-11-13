"""Owned disposable PostgreSQL/Keycloak harness. No inherited database URLs."""

import argparse
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx2 as httpx
import psycopg

PREFIX = "animetron-oidc-478745d5-"
ROOT = Path(__file__).resolve().parents[1]


def docker(*args, env=None):
    result = subprocess.run(
        ["docker", *args], env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        # Docker failures may echo command/env data: do not print stderr.
        raise RuntimeError("Owned Docker operation failed: " + args[0])
    return result.stdout.strip()


def wait_for(check):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            return check()
        except (httpx.HTTPError, psycopg.Error):
            time.sleep(1)
    raise RuntimeError("Isolated dependency did not become ready within 120 seconds")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ)
    # Never inherit a production/test URL, auth setting or proxy.
    for key in list(env):
        if key.startswith("ANIMETRON_") or key.lower().endswith("_proxy"):
            env.pop(key)
    temporary = ROOT.parent / "data" / "oidc-test-temp"
    temporary.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
               PYTHONPATH=str(ROOT))
    env["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
    env["KC_DB_PASSWORD"] = env["POSTGRES_PASSWORD"]
    env["KC_BOOTSTRAP_ADMIN_USERNAME"] = "test-admin"
    env["KC_BOOTSTRAP_ADMIN_PASSWORD"] = secrets.token_urlsafe(32)
    network, db, kc = PREFIX + "network", PREFIX + "postgres", PREFIX + "keycloak"
    created = []
    network_created = False
    try:
        # Docker 29 internal bridges omit host port mappings. A dedicated bridge
        # with exclusively loopback bindings permits host-side acceptance checks.
        docker("network", "create", network)
        network_created = True
        docker("run", "--detach", "--name", db, "--network", network,
               "--network-alias", "postgres", "--publish", "127.0.0.1::5432",
               "--memory", "512m", "--cpus", "2",
               "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB=animetron",
               "postgres:18", env=env)
        created.append(db)
        port = docker("port", db, "5432/tcp").split(":")[-1]
        url = f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/animetron"
        connection = wait_for(lambda: psycopg.connect(url, connect_timeout=3, autocommit=True))
        with connection:
            connection.execute("CREATE DATABASE keycloak")
        env["ANIMETRON_TEST_DATABASE_URL"] = url.replace(
            "postgresql://", "postgresql+psycopg://"
        )
        migration_env = dict(env, ANIMETRON_DATABASE_URL=env["ANIMETRON_TEST_DATABASE_URL"])
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=ROOT, env=migration_env, check=True)
        print("PostgreSQL image:", docker("inspect", "--format", "{{.Image}}", db), flush=True)
        if not args.storage:
            docker("run", "--detach", "--name", kc, "--network", network,
                   "--publish", "127.0.0.1::8080", "--memory", "1g", "--cpus", "2",
                   "-e", "KC_DB=postgres", "-e", "KC_DB_URL=jdbc:postgresql://postgres/keycloak",
                   "-e", "KC_DB_USERNAME=postgres", "-e", "KC_DB_PASSWORD",
                   "-e", "KC_BOOTSTRAP_ADMIN_USERNAME", "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD",
                   "quay.io/keycloak/keycloak:26.8.2", "start-dev", env=env)
            created.append(kc)
            port = docker("port", kc, "8080/tcp").split(":")[-1]
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=5, trust_env=False) as client:
                def ready():
                    response = client.get(base + "/realms/master/.well-known/openid-configuration")
                    response.raise_for_status()
                    return response
                wait_for(ready)
                response = client.post(base + "/realms/master/protocol/openid-connect/token", data={
                    "client_id": "admin-cli", "grant_type": "password",
                    "username": env["KC_BOOTSTRAP_ADMIN_USERNAME"],
                    "password": env["KC_BOOTSTRAP_ADMIN_PASSWORD"],
                })
                response.raise_for_status()
                headers = {"Authorization": "Bearer " + response.json()["access_token"]}
                env["ANIMETRON_TEST_OIDC_CLIENT_SECRET"] = secrets.token_urlsafe(32)
                env["ANIMETRON_TEST_OIDC_PASSWORD"] = secrets.token_urlsafe(32)
                owner = "5b0b743e-739b-4dfe-8b58-b7678832ed28"
                response = client.post(base + "/admin/realms", headers=headers, json={
                    "realm": "animetron-test", "enabled": True, "sslRequired": "none",
                    "registrationAllowed": False, "bruteForceProtected": True,
                    "clients": [{
                        "clientId": "animetron", "enabled": True, "protocol": "openid-connect",
                        "publicClient": False, "secret": env["ANIMETRON_TEST_OIDC_CLIENT_SECRET"],
                        "standardFlowEnabled": True, "directAccessGrantsEnabled": False,
                        "redirectUris": ["https://control.example/api/v1/auth/callback"],
                        "webOrigins": ["https://control.example"],
                        "attributes": {"pkce.code.challenge.method": "S256"},
                    }],
                    "users": [{
                        "id": owner, "username": "test-owner", "enabled": True,
                        "emailVerified": True, "firstName": "Test", "lastName": "Owner",
                        "email": "owner@example.invalid",
                        "credentials": [{"type": "password", "temporary": False,
                                         "value": env["ANIMETRON_TEST_OIDC_PASSWORD"]}],
                    }],
                })
                response.raise_for_status()
                env["ANIMETRON_TEST_OIDC_ISSUER"] = base + "/realms/animetron-test"
                env["ANIMETRON_TEST_OIDC_OWNER"] = owner
            print("Keycloak image:", docker("inspect", "--format", "{{.Image}}", kc), flush=True)
        selection = ["tests/test_auth_storage.py"] if args.storage else ["tests"]
        results = []
        for command in (
            # Failure output must not serialize browser URLs or fixture secrets.
            # Assertions remain intact; only traceback presentation is redacted.
            [sys.executable, "-m", "pytest", *selection, "-q", "--tb=no", "--basetemp", str(temporary / "pytest")],
            [sys.executable, "-m", "ruff", "check", "app", "tests"],
            [sys.executable, "-m", "mypy", "--platform", "linux", "app"],
        ):
            results.append(subprocess.run(command, cwd=ROOT, env=env, check=False).returncode)
        if any(results) and kc in created:
            # Provider error *codes* only, never log lines (codes/tokens/credentials
            # and client query parameters may otherwise occur in server output).
            logs = docker("logs", kc)
            print("Provider diagnostic error codes:",
                  sorted(set(re.findall(r'error="([a-z_]+)"', logs))), flush=True)
        if not args.storage:
            subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0005_artifact_metadata"],
                           cwd=ROOT, env=migration_env, check=True)
            subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                           cwd=ROOT, env=migration_env, check=True)
        return max(results)
    finally:
        for name in reversed(created):
            docker("rm", "--force", "--volumes", name)
            print("Removed owned container (including anonymous volumes):", name, flush=True)
        if network_created:
            docker("network", "rm", network)
            print("Removed owned network:", network, flush=True)


if __name__ == "__main__":
    sys.exit(main())
