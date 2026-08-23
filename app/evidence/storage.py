from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.evidence.models import (
    EvidenceManifest,
    EvidenceRetention,
)


class EvidenceStore(Protocol):
    """Storage contract for immutable evidence payloads."""

    def publish(
        self,
        payload: bytes,
        *,
        artifact_id: str,
        artifact_type: str,
        source_commit_sha: str,
        schema_version: str,
        retention: EvidenceRetention,
    ) -> EvidenceManifest: ...

    def read(self, manifest: EvidenceManifest) -> bytes: ...


def _manifest_for(
    payload: bytes,
    *,
    artifact_id: str,
    artifact_type: str,
    source_commit_sha: str,
    schema_version: str,
    retention: EvidenceRetention,
    artifact_uri: str,
) -> EvidenceManifest:
    return EvidenceManifest(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        source_commit_sha=source_commit_sha,
        created_at=datetime.now(UTC),
        content_hash=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        schema_version=schema_version,
        retention=retention,
        artifact_uri=artifact_uri,
    )


class LocalFilesystemEvidenceStore:
    """Local development store with atomic, non-overwriting publication."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def publish(
        self,
        payload: bytes,
        *,
        artifact_id: str,
        artifact_type: str,
        source_commit_sha: str,
        schema_version: str,
        retention: EvidenceRetention,
    ) -> EvidenceManifest:
        manifest = _manifest_for(
            payload,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            source_commit_sha=source_commit_sha,
            schema_version=schema_version,
            retention=retention,
            artifact_uri=f"local://{artifact_id}",
        )
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / artifact_id
        destination.mkdir(parents=True, exist_ok=False)
        payload_path = destination / "payload"
        try:
            self._atomic_create(payload_path, payload)
        except BaseException:
            raise
        return manifest

    def read(self, manifest: EvidenceManifest) -> bytes:
        if not manifest.artifact_uri.startswith("local://"):
            raise ValueError("local filesystem store cannot read a non-local artifact URI")
        artifact_id = manifest.artifact_uri.removeprefix("local://")
        payload_path = self.root / artifact_id / "payload"
        resolved = payload_path.resolve()
        if self.root not in resolved.parents:
            raise ValueError("artifact URI escapes the local evidence root")
        return resolved.read_bytes()

    @staticmethod
    def _atomic_create(destination: Path, payload: bytes) -> None:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".payload-", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            raise FileExistsError(f"evidence payload already exists: {destination}") from None
        finally:
            temporary_path.unlink(missing_ok=True)


class S3Client(Protocol):
    """Small boto3-compatible surface, keeping the production dependency injectable."""

    def put_object(self, **kwargs: object) -> object: ...

    def get_object(self, **kwargs: object) -> Mapping[str, bytes | ReadableBody]: ...


class ReadableBody(Protocol):
    def read(self) -> bytes: ...


class S3CompatibleEvidenceStore:
    """S3-compatible adapter; callers provide their configured SDK client."""

    def __init__(self, client: S3Client, bucket: str, prefix: str = "evidence") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def publish(
        self,
        payload: bytes,
        *,
        artifact_id: str,
        artifact_type: str,
        source_commit_sha: str,
        schema_version: str,
        retention: EvidenceRetention,
    ) -> EvidenceManifest:
        key = self._key(artifact_id)
        manifest = _manifest_for(
            payload,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            source_commit_sha=source_commit_sha,
            schema_version=schema_version,
            retention=retention,
            artifact_uri=f"s3://{self.bucket}/{key}",
        )
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            IfNoneMatch="*",
            Metadata={
                "sha256": manifest.content_hash,
                "schema-version": manifest.schema_version,
            },
        )
        return manifest

    def read(self, manifest: EvidenceManifest) -> bytes:
        expected_prefix = f"s3://{self.bucket}/"
        if not manifest.artifact_uri.startswith(expected_prefix):
            raise ValueError("S3 evidence store cannot read a different bucket")
        key = manifest.artifact_uri.removeprefix(expected_prefix)
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        stream = response.get("Body")
        if isinstance(stream, bytes):
            return stream
        if stream is None:
            raise TypeError("S3 client returned an empty object body")
        return stream.read()

    def _key(self, artifact_id: str) -> str:
        return f"{self.prefix}/{artifact_id}" if self.prefix else artifact_id
