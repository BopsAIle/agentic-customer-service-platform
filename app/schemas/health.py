from typing import Literal

from pydantic import BaseModel

from app.health import OperationalHealthState


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]


class HealthDependencyResponse(BaseModel):
    name: str
    status: str
    latency_ms: float | None = None
    detail: str


class OperationalMetricsResponse(BaseModel):
    request_count: int
    error_rate: float
    average_duration_ms: float
    retry_count: int
    retry_exhausted_count: int
    circuit_open_count: int


class HealthDetailsResponse(BaseModel):
    status: OperationalHealthState
    version: str
    deployment_id: str
    dependencies: list[HealthDependencyResponse]
    latency_summary: dict[str, float]
    metrics: OperationalMetricsResponse
