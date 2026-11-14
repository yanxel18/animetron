"""Owned disposable PostgreSQL/Keycloak harness. No inherited database URLs."""

import argparse
import hashlib
import json
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
    parser.add_argument("--pytest-file", choices=[
        "tests/test_reviews_api.py", "tests/test_schedules_api.py",
        "tests/test_run_requests.py", "tests/test_execution_bindings.py",
    ])
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
    created = {}
    network_id = None
    owner = secrets.token_hex(16)
    owner_token = secrets.token_urlsafe(32)
    labels = ("--label", "animetron.session=478745d5",
              "--label", "animetron.oidc.owner=" + owner)

    def verify_container(container_id):
        actual = json.loads(docker("inspect", "--format", "{{json .Config.Labels}}", container_id))
        if (
            docker("inspect", "--format", "{{.Id}}", container_id) != container_id
            or actual.get("animetron.session") != "478745d5"
            or actual.get("animetron.oidc.owner") != owner
        ):
            raise RuntimeError("Owned test container identity verification failed")

    try:
        # Docker 29 internal bridges omit host port mappings. A dedicated bridge
        # with exclusively loopback bindings permits host-side acceptance checks.
        network_id = docker("network", "create", *labels, network)
        print("Owned network ID:", network_id, "owner:", owner, flush=True)
        created[db] = docker("run", "--pull=never", "--detach", "--name", db, *labels, "--network", network_id,
               "--network-alias", "postgres", "--publish", "127.0.0.1::5432",
               "--memory", "512m", "--cpus", "2",
               "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB=animetron",
               "postgres:18", env=env)
        verify_container(created[db])
        print("Owned PostgreSQL ID:", created[db], "owner:", owner, flush=True)
        print("Owned PostgreSQL volumes:", docker(
            "inspect", "--format", "{{range .Mounts}}{{if eq .Type \"volume\"}}{{.Name}} {{end}}{{end}}",
            created[db],
        ), flush=True)
        port = docker("port", created[db], "5432/tcp").split(":")[-1]
        url = f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/animetron"
        connection = wait_for(lambda: psycopg.connect(url, connect_timeout=3, autocommit=True))
        with connection:
            connection.execute("CREATE DATABASE keycloak")
            connection.execute("CREATE SCHEMA animetron_oidc_test_guard")
            connection.execute(
                "CREATE TABLE animetron_oidc_test_guard.ownership ("
                "singleton boolean PRIMARY KEY CHECK (singleton), "
                "owner_id text NOT NULL, token_hash text NOT NULL, "
                "container_id text NOT NULL, database_name text NOT NULL)"
            )
            connection.execute(
                "INSERT INTO animetron_oidc_test_guard.ownership VALUES "
                "(true, %s, %s, %s, current_database())",
                (owner, hashlib.sha256(owner_token.encode()).hexdigest(), created[db]),
            )
        env["ANIMETRON_TEST_DATABASE_OWNER_ID"] = owner
        env["ANIMETRON_TEST_DATABASE_OWNER_TOKEN"] = owner_token
        env["ANIMETRON_TEST_DATABASE_CONTAINER_ID"] = created[db]
        env["ANIMETRON_TEST_DATABASE_URL"] = url.replace(
            "postgresql://", "postgresql+psycopg://"
        )
        migration_env = dict(env, ANIMETRON_DATABASE_URL=env["ANIMETRON_TEST_DATABASE_URL"])
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=ROOT, env=migration_env, check=True)
        # The harness marker is deliberately outside application metadata.
        subprocess.run([sys.executable, "-m", "alembic", "check"],
                       cwd=ROOT, env=migration_env, check=True)
        print("PostgreSQL image:", docker("inspect", "--format", "{{.Image}}", created[db]), flush=True)
        if not args.storage:
            created[kc] = docker("run", "--pull=never", "--detach", "--name", kc, *labels, "--network", network_id,
                   "--publish", "127.0.0.1::8080", "--memory", "1g", "--cpus", "2",
                   "-e", "KC_DB=postgres", "-e", "KC_DB_URL=jdbc:postgresql://postgres/keycloak",
                   "-e", "KC_DB_USERNAME=postgres", "-e", "KC_DB_PASSWORD",
                   "-e", "KC_BOOTSTRAP_ADMIN_USERNAME", "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD",
                   "quay.io/keycloak/keycloak:26.8.2", "start-dev", env=env)
            verify_container(created[kc])
            print("Owned Keycloak ID:", created[kc], "owner:", owner, flush=True)
            print("Owned Keycloak volumes:", docker(
                "inspect", "--format", "{{range .Mounts}}{{if eq .Type \"volume\"}}{{.Name}} {{end}}{{end}}",
                created[kc],
            ), flush=True)
            port = docker("port", created[kc], "8080/tcp").split(":")[-1]
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
                realm_owner = "5b0b743e-739b-4dfe-8b58-b7678832ed28"
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
                        "id": realm_owner, "username": "test-owner", "enabled": True,
                        "emailVerified": True, "firstName": "Test", "lastName": "Owner",
                        "email": "owner@example.invalid",
                        "credentials": [{"type": "password", "temporary": False,
                                         "value": env["ANIMETRON_TEST_OIDC_PASSWORD"]}],
                    }],
                })
                response.raise_for_status()
                env["ANIMETRON_TEST_OIDC_ISSUER"] = base + "/realms/animetron-test"
                env["ANIMETRON_TEST_OIDC_OWNER"] = realm_owner
            print("Keycloak image:", docker("inspect", "--format", "{{.Image}}", created[kc]), flush=True)
        selection = (
            [args.pytest_file] if args.pytest_file
            else ["tests/test_auth_storage.py"] if args.storage
            else ["tests"]
        )
        traceback_mode = "--tb=short" if args.pytest_file else "--tb=no"
        results = []
        for command in (
            # Failure output must not serialize browser URLs or fixture secrets.
            # Assertions remain intact; only traceback presentation is redacted.
            [sys.executable, "-m", "pytest", *selection, "-q", traceback_mode, "--basetemp", str(temporary / "pytest")],
            [sys.executable, "-m", "ruff", "check", "--no-cache", "app", "tests", "migrations"],
            [sys.executable, "-m", "mypy", "--platform", "linux", "app"],
        ):
            results.append(subprocess.run(command, cwd=ROOT, env=env, check=False).returncode)
        if any(results) and kc in created:
            # Provider error *codes* only, never log lines (codes/tokens/credentials
            # and client query parameters may otherwise occur in server output).
            logs = docker("logs", created[kc])
            print("Provider diagnostic error codes:",
                  sorted(set(re.findall(r'error="([a-z_]+)"', logs))), flush=True)
        if not args.storage:
            subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0005_artifact_metadata"],
                           cwd=ROOT, env=migration_env, check=True)
            subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                           cwd=ROOT, env=migration_env, check=True)
        return max(results)
    finally:
        for name, container_id in reversed(tuple(created.items())):
            verify_container(container_id)
            docker("rm", "--force", "--volumes", container_id)
            print("Removed owned container (including anonymous volumes):", name, flush=True)
        if network_id:
            network_labels = json.loads(docker(
                "network", "inspect", "--format", "{{json .Labels}}", network_id,
            ))
            if (
                docker("network", "inspect", "--format", "{{.Id}}", network_id) != network_id
                or network_labels.get("animetron.session") != "478745d5"
                or network_labels.get("animetron.oidc.owner") != owner
            ):
                raise RuntimeError("Owned test network identity verification failed")
            docker("network", "rm", network_id)
            print("Removed owned network:", network, flush=True)


if __name__ == "__main__":
    sys.exit(main())
