"""Verify local PostgreSQL and artifact-byte backup/restore in disposable Docker resources."""

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.request
import uuid

POSTGRES_IMAGE = "postgres:18"
PYTHON_IMAGE = "python:3.12-slim"


class RecoveryCheck:
    def __init__(self):
        self.owner = secrets.token_hex(16)
        self.prefix = "animetron-recovery-" + uuid.uuid4().hex
        self.labels = (
            "--label",
            "animetron.test=platform-recovery",
            "--label",
            "animetron.test.owner=" + self.owner,
        )
        self.container_names = []
        self.volume_names = []
        self.network_names = []
        self.password = secrets.token_urlsafe(32)
        self.environment = dict(os.environ)
        for key in list(self.environment):
            if key.startswith("ANIMETRON_") or key.lower().endswith("_proxy"):
                self.environment.pop(key)
        self.environment["POSTGRES_PASSWORD"] = self.password

    @staticmethod
    def docker(*args, input_bytes=None, binary_output=False, env=None):
        result = subprocess.run(
            ["docker", *args],
            input=input_bytes,
            capture_output=True,
            text=input_bytes is None and not binary_output,
            env=env,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"Docker {args[0]} failed with exit code {result.returncode}"
            )
        return result.stdout.strip() if isinstance(result.stdout, str) else result.stdout

    def inspect_container(self, target):
        return json.loads(self.docker("inspect", target))[0]

    def verify_container(self, target):
        details = self.inspect_container(target)
        labels = details["Config"]["Labels"] or {}
        if (
            labels.get("animetron.test") != "platform-recovery"
            or labels.get("animetron.test.owner") != self.owner
        ):
            raise RuntimeError("Docker container ownership check failed")
        return details

    def verify_named_resource(self, kind, name):
        if kind == "volume":
            details = json.loads(self.docker("volume", "inspect", name))[0]
        else:
            details = json.loads(self.docker("network", "inspect", name))[0]
        labels = details.get("Labels") or {}
        if (
            details["Name"] != name
            or labels.get("animetron.test") != "platform-recovery"
            or labels.get("animetron.test.owner") != self.owner
        ):
            raise RuntimeError(f"Docker {kind} ownership check failed")
        return details

    def create_network(self, suffix, internal=False):
        name = self.prefix + "-" + suffix
        self.network_names.append(name)
        args = ["network", "create", *self.labels]
        if internal:
            args.append("--internal")
        args.append(name)
        self.docker(*args)
        self.verify_named_resource("network", name)
        return name

    def create_volume(self, suffix):
        name = self.prefix + "-" + suffix
        self.volume_names.append(name)
        self.docker("volume", "create", *self.labels, name)
        self.verify_named_resource("volume", name)
        return name

    def create_container(self, suffix, *args, env=None):
        name = self.prefix + "-" + suffix
        self.container_names.append(name)
        container_id = self.docker(
            "run",
            "--pull=never",
            "--name",
            name,
            *self.labels,
            *args,
            env=env,
        )
        self.verify_container(container_id)
        return container_id

    def run_helper(self, suffix, *args):
        name = self.prefix + "-" + suffix
        self.container_names.append(name)
        container_id = self.docker(
            "create",
            "--pull=never",
            "--name",
            name,
            *self.labels,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            *args,
        )
        self.verify_container(container_id)
        output = self.docker("start", "--attach", container_id)
        if self.inspect_container(container_id)["State"]["ExitCode"] != 0:
            raise RuntimeError("Disposable Docker helper failed")
        return output

    def wait_for_postgres(self, container_id):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["docker", "exec", container_id, "pg_isready", "-U", "postgres"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError("Disposable PostgreSQL did not become ready")

    def create_postgres(self, suffix, network):
        container_id = self.create_container(
            suffix,
            "--detach",
            "--network",
            network,
            "--memory",
            "512m",
            "--cpus",
            "2",
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            "POSTGRES_DB=animetron",
            POSTGRES_IMAGE,
            env=self.environment,
        )
        self.wait_for_postgres(container_id)
        details = self.verify_container(container_id)
        bindings = details["HostConfig"].get("PortBindings") or {}
        if bindings:
            raise RuntimeError("PostgreSQL unexpectedly has a published host port")
        return container_id

    def cleanup(self):
        errors = []
        for name in reversed(self.container_names):
            try:
                matches = self.docker(
                    "ps", "-aq", "--filter", "name=" + name
                ).splitlines()
                matches = [
                    container_id
                    for container_id in matches
                    if self.inspect_container(container_id)["Name"] == "/" + name
                ]
                if not matches:
                    continue
                if len(matches) != 1:
                    raise RuntimeError("Owned container name was not unique")
                container_id = matches[0]
                details = self.verify_container(container_id)
                if details["Name"] != "/" + name:
                    raise RuntimeError("Owned container name verification failed")
                self.docker("rm", "--force", "--volumes", container_id)
            except RuntimeError as error:
                errors.append(str(error))

        for name in reversed(self.volume_names):
            try:
                matches = self.docker(
                    "volume", "ls", "-q", "--filter", "name=" + name
                ).splitlines()
                matches = [match for match in matches if match == name]
                if not matches:
                    continue
                if matches != [name]:
                    raise RuntimeError("Owned volume name was not unique")
                self.verify_named_resource("volume", name)
                self.docker("volume", "rm", name)
            except RuntimeError as error:
                errors.append(str(error))

        for name in reversed(self.network_names):
            try:
                listed = self.docker(
                    "network", "ls", "-q", "--filter", "name=" + name
                ).splitlines()
                matches = []
                for network_id in listed:
                    details = json.loads(
                        self.docker("network", "inspect", network_id)
                    )[0]
                    if details["Name"] == name:
                        matches.append(details)
                if not matches:
                    continue
                if len(matches) != 1:
                    raise RuntimeError("Owned network name was not unique")
                self.verify_named_resource("network", name)
                self.docker("network", "rm", matches[0]["Id"])
            except RuntimeError as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("Docker cleanup failed: " + "; ".join(errors))

    def run(self):
        data_network = self.create_network("data", internal=True)
        gateway_network = self.create_network("gateway")
        source_volume = self.create_volume("artifact-source")
        restored_volume = self.create_volume("artifact-restored")
        source_db = self.create_postgres("postgres-source", data_network)

        gateway_code = (
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_response(200)\n"
            "        self.end_headers()\n"
            "        self.wfile.write(b'ok')\n"
            "    def log_message(self, format, *args):\n"
            "        pass\n"
            "HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()\n"
        )
        gateway = self.create_container(
            "gateway",
            "--detach",
            "--network",
            gateway_network,
            "--publish",
            "127.0.0.1::8000",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "10001:10001",
            PYTHON_IMAGE,
            "python",
            "-c",
            gateway_code,
        )
        self.docker("network", "connect", data_network, gateway)

        networks = self.verify_container(source_db)["NetworkSettings"]["Networks"]
        if set(networks) != {data_network}:
            raise RuntimeError("PostgreSQL is not isolated to the private data network")
        gateway_networks = self.verify_container(gateway)["NetworkSettings"]["Networks"]
        if set(gateway_networks) != {data_network, gateway_network}:
            raise RuntimeError("Test gateway is not attached to both test networks")

        binding = self.docker("port", gateway, "8000/tcp").splitlines()
        if len(binding) != 1 or not binding[0].startswith("127.0.0.1:"):
            raise RuntimeError("Test gateway is not published exclusively on loopback")
        host_port = binding[0].rsplit(":", 1)[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{host_port}/healthz", timeout=10) as response:
            if response.status != 200 or response.read() != b"ok":
                raise RuntimeError("Loopback test gateway health check failed")

        artifact_id = str(uuid.uuid4())
        locator = "artifacts/" + uuid.UUID(artifact_id).hex
        payload = b"AnimeTron disposable recovery check\n"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory(prefix="animetron-recovery-") as directory:
            payload_path = os.path.join(directory, "payload.bin")
            archive_path = os.path.join(directory, "artifacts.tar")
            dump_path = os.path.join(directory, "metadata.dump")
            with open(payload_path, "wb") as stream:
                stream.write(payload)

            insert = (
                "CREATE TABLE artifact_metadata ("
                "id uuid PRIMARY KEY, sha256 text NOT NULL, byte_size bigint NOT NULL, "
                "storage_locator text NOT NULL); "
                "INSERT INTO artifact_metadata VALUES "
                f"('{artifact_id}', '{digest}', {len(payload)}, '{locator}')"
            )
            self.docker(
                "exec",
                source_db,
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "animetron",
                "-c",
                insert,
            )
            source_seed = (
                "import pathlib; "
                "p=pathlib.Path('/data')/'" + locator + "'; "
                "p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_bytes(pathlib.Path('/backup/payload.bin').read_bytes())"
            )
            self.run_helper(
                "seed-bytes",
                "--mount",
                f"type=volume,source={source_volume},target=/data",
                "--mount",
                f"type=bind,source={directory},target=/backup,readonly",
                "--entrypoint",
                "python",
                PYTHON_IMAGE,
                "-c",
                source_seed,
            )
            source_hash = self.run_helper(
                "hash-source",
                "--mount",
                f"type=volume,source={source_volume},target=/data,readonly",
                "--entrypoint",
                "python",
                PYTHON_IMAGE,
                "-c",
                "import hashlib,pathlib; print(hashlib.sha256("
                "pathlib.Path('/data/" + locator + "').read_bytes()).hexdigest())",
            )
            if source_hash != digest:
                raise RuntimeError("Source artifact bytes do not match metadata")

            archive_code = (
                "import tarfile; "
                "a=tarfile.open('/backup/artifacts.tar','w'); "
                "a.add('/data/" + locator + "',arcname='" + locator + "'); "
                "a.close()"
            )
            self.run_helper(
                "backup-bytes",
                "--mount",
                f"type=volume,source={source_volume},target=/data,readonly",
                "--mount",
                f"type=bind,source={directory},target=/backup",
                "--entrypoint",
                "python",
                PYTHON_IMAGE,
                "-c",
                archive_code,
            )
            if not os.path.isfile(archive_path) or os.path.getsize(archive_path) == 0:
                raise RuntimeError("Artifact-byte backup archive was not created")

            dump = self.docker(
                "exec", source_db, "pg_dump", "-U", "postgres", "--format=custom",
                "animetron", binary_output=True,
            )
            with open(dump_path, "wb") as stream:
                stream.write(dump)
            with open(dump_path, "rb") as stream:
                dump = stream.read()

            restore_db = self.create_postgres("postgres-restored", data_network)
            restored = self.docker(
                "exec",
                "-i",
                restore_db,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "animetron",
                input_bytes=dump,
            )
            if restored:
                raise RuntimeError("PostgreSQL restore unexpectedly emitted output")

            restore_code = (
                "import tarfile\n"
                "a=tarfile.open('/backup/artifacts.tar','r')\n"
                "m=a.getmembers()\n"
                "if len(m)!=1 or m[0].name!='" + locator + "' or not m[0].isfile():\n"
                "    raise RuntimeError('Unexpected artifact archive contents')\n"
                "a.extractall('/data',members=m,filter='data')\n"
                "a.close()\n"
            )
            self.run_helper(
                "restore-bytes",
                "--mount",
                f"type=volume,source={restored_volume},target=/data",
                "--mount",
                f"type=bind,source={directory},target=/backup,readonly",
                "--entrypoint",
                "python",
                PYTHON_IMAGE,
                "-c",
                restore_code,
            )
            restored_hash = self.run_helper(
                "hash-restored",
                "--mount",
                f"type=volume,source={restored_volume},target=/data,readonly",
                "--entrypoint",
                "python",
                PYTHON_IMAGE,
                "-c",
                "import hashlib,pathlib; print(hashlib.sha256("
                "pathlib.Path('/data/" + locator + "').read_bytes()).hexdigest())",
            )
            if restored_hash != digest:
                raise RuntimeError("Restored artifact bytes failed SHA-256 verification")

            restored_row = self.docker(
                "exec",
                restore_db,
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "animetron",
                "-t",
                "-A",
                "-F",
                "|",
                "-c",
                "SELECT id::text, sha256, byte_size, storage_locator "
                "FROM artifact_metadata",
            )
            expected_row = f"{artifact_id}|{digest}|{len(payload)}|{locator}"
            if restored_row != expected_row:
                raise RuntimeError("Restored metadata does not match the test artifact")

        print(
            "PASS: PostgreSQL metadata and artifact bytes restored into fresh "
            "resources with matching SHA-256; database remained private and "
            "the test gateway was reachable only through its loopback binding."
        )


def main():
    check = RecoveryCheck()
    try:
        check.run()
    finally:
        check.cleanup()


if __name__ == "__main__":
    main()
