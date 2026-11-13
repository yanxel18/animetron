from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="AnimeTron API", docs_url=None, redoc_url=None)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@app.get("/api/v1/health")
async def health() -> HealthResponse:
    return HealthResponse()
