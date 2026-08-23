from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceRetentionClass(StrEnum):
    STANDARD = "standard"
    RELEASE = "release"
    SHORT = "short"


class EvidenceRetention(BaseModel):
    """Retention metadata that is safe to keep alongside an evidence manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    retention_class: EvidenceRetentionClass
    retention_days: int | None = Field(default=None, ge=1)
    immutable: bool = True

    @field_validator("immutable")
    @classmethod
    def require_immutable_retention(cls, value: bool) -> bool:
        if not value:
            raise ValueError("external evidence must use immutable retention")
        return value


class EvidenceManifest(BaseModel):
    """Immutable, privacy-safe identity for one externally stored evidence payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    artifact_type: str = Field(
        min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    source_commit_sha: str = Field(pattern=r"^[0-9a-fA-F]{40,64}$")
    created_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size: int = Field(ge=0)
    schema_version: str = Field(
        min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    retention: EvidenceRetention
    artifact_uri: str = Field(min_length=1, max_length=512)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include an explicit timezone")
        return value

    @field_validator("artifact_uri")
    @classmethod
    def require_supported_uri(cls, value: str) -> str:
        if not (value.startswith("local://") or value.startswith("s3://")):
            raise ValueError("artifact_uri must use local:// or s3://")
        if any(character.isspace() for character in value):
            raise ValueError("artifact_uri must not contain whitespace")
        return value
