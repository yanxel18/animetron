import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
EXPORTER = BACKEND / "scripts" / "export_openapi.py"


def test_exports_local_openapi_without_registering_a_public_schema_route():
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONPATH": str(BACKEND),
    }
    result = subprocess.run(
        [sys.executable, str(EXPORTER)],
        check=False,
        capture_output=True,
        cwd=BACKEND,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    schema = json.loads(result.stdout)
    assert schema["paths"]["/api/v1/health"]["get"]["responses"]["200"]
    artifact_path = "/api/v1/artifacts/{id}"
    assert set(schema["paths"][artifact_path]) == {"get"}
    assert schema["paths"][artifact_path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]
    assert "/api/v1/runs/{id}" in schema["paths"]
    assert "/api/v1/runs/{id}/events" in schema["paths"]
    assert "/api/v1/runs/{id}/cancellations" in schema["paths"]
    revision_path = "/api/v1/workflows/{id}/revisions/{revision}"
    assert set(schema["paths"][revision_path]) == {"get"}
    revision_read = schema["paths"][revision_path]["get"]
    assert revision_read["responses"]["200"]["content"]["application/json"]
    run_path = "/api/v1/workflows/{id}/runs"
    assert set(schema["paths"][run_path]) == {"post"}
    run_create = schema["paths"][run_path]["post"]
    idempotency_key = [
        parameter
        for parameter in run_create["parameters"]
        if parameter["in"] == "header" and parameter["name"] == "Idempotency-Key"
    ]
    assert len(idempotency_key) == 1
    assert idempotency_key[0]["required"] is True
    assert run_create["requestBody"]["required"] is True
    assert run_create["responses"]["202"]["headers"]["Location"]["schema"] == {
        "type": "string"
    }
    assert "/openapi.json" not in schema["paths"]
