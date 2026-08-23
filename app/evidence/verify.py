from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.evidence.models import EvidenceManifest
from app.evidence.storage import EvidenceStore


class EvidenceVerificationError(ValueError):
    """Raised when an evidence manifest or payload cannot be verified."""


def load_manifest(path: Path) -> EvidenceManifest:
    try:
        return EvidenceManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, json.JSONDecodeError) as error:
        raise EvidenceVerificationError(f"invalid evidence manifest: {path}") from error


def verify_evidence(
    manifest: EvidenceManifest,
    store: EvidenceStore,
    *,
    expected_source_sha: str | None = None,
    expected_schema_version: str | None = None,
) -> bytes:
    if expected_source_sha is not None and manifest.source_commit_sha != expected_source_sha:
        raise EvidenceVerificationError("source commit identity mismatch")
    if expected_schema_version is not None and manifest.schema_version != expected_schema_version:
        raise EvidenceVerificationError("evidence schema version mismatch")
    try:
        payload = store.read(manifest)
    except (OSError, TypeError, ValueError) as error:
        raise EvidenceVerificationError("evidence payload unavailable") from error
    if len(payload) != manifest.size:
        raise EvidenceVerificationError("evidence size mismatch")
    if hashlib.sha256(payload).hexdigest() != manifest.content_hash:
        raise EvidenceVerificationError("evidence content hash mismatch")
    _validate_payload_schema(payload, manifest.schema_version)
    return payload


def _validate_payload_schema(payload: bytes, manifest_schema_version: str) -> None:
    """Validate an optional self-describing JSON payload without inspecting its contents."""

    try:
        decoded: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(decoded, dict) or "schema_version" not in decoded:
        return
    if decoded["schema_version"] != manifest_schema_version:
        raise EvidenceVerificationError("payload schema version mismatch")
