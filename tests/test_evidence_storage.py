from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from app.evidence.models import EvidenceRetention, EvidenceRetentionClass
from app.evidence.storage import (
    LocalFilesystemEvidenceStore,
    ReadableBody,
    S3CompatibleEvidenceStore,
)
from app.evidence.verify import EvidenceVerificationError, verify_evidence

SOURCE_SHA = "a" * 40
SCHEMA = "evaluation_attempts_v1"


def retention() -> EvidenceRetention:
    return EvidenceRetention(
        retention_class=EvidenceRetentionClass.RELEASE,
        retention_days=365,
    )


def test_local_publish_and_deterministic_verification(tmp_path: Path) -> None:
    payload = b'{"schema_version":"evaluation_attempts_v1","count":2}\n'
    store = LocalFilesystemEvidenceStore(tmp_path / "payloads")
    manifest = store.publish(
        payload,
        artifact_id="run-001-attempts",
        artifact_type="evaluation_attempts",
        source_commit_sha=SOURCE_SHA,
        schema_version=SCHEMA,
        retention=retention(),
    )

    assert manifest.content_hash == hashlib.sha256(payload).hexdigest()
    assert manifest.size == len(payload)
    assert (
        verify_evidence(
            manifest,
            store,
            expected_source_sha=SOURCE_SHA,
            expected_schema_version=SCHEMA,
        )
        == payload
    )

    with pytest.raises(FileExistsError):
        store.publish(
            payload,
            artifact_id="run-001-attempts",
            artifact_type="evaluation_attempts",
            source_commit_sha=SOURCE_SHA,
            schema_version=SCHEMA,
            retention=retention(),
        )


def test_missing_artifact_fails_closed(tmp_path: Path) -> None:
    store = LocalFilesystemEvidenceStore(tmp_path / "payloads")
    manifest = store.publish(
        b"immutable evidence",
        artifact_id="missing-test",
        artifact_type="summary",
        source_commit_sha=SOURCE_SHA,
        schema_version=SCHEMA,
        retention=retention(),
    )
    (tmp_path / "payloads" / "missing-test" / "payload").unlink()

    with pytest.raises(EvidenceVerificationError, match="payload unavailable"):
        verify_evidence(manifest, store, expected_source_sha=SOURCE_SHA)


def test_corrupted_artifact_fails_hash_validation(tmp_path: Path) -> None:
    store = LocalFilesystemEvidenceStore(tmp_path / "payloads")
    manifest = store.publish(
        b"original",
        artifact_id="corrupt-test",
        artifact_type="summary",
        source_commit_sha=SOURCE_SHA,
        schema_version=SCHEMA,
        retention=retention(),
    )
    (tmp_path / "payloads" / "corrupt-test" / "payload").write_bytes(b"corrupt!")

    with pytest.raises(EvidenceVerificationError, match="hash mismatch"):
        verify_evidence(manifest, store)


def test_source_and_schema_mismatch_fail_closed(tmp_path: Path) -> None:
    store = LocalFilesystemEvidenceStore(tmp_path / "payloads")
    manifest = store.publish(
        b"payload",
        artifact_id="identity-test",
        artifact_type="summary",
        source_commit_sha=SOURCE_SHA,
        schema_version=SCHEMA,
        retention=retention(),
    )

    with pytest.raises(EvidenceVerificationError, match="source commit identity"):
        verify_evidence(manifest, store, expected_source_sha="b" * 40)
    with pytest.raises(EvidenceVerificationError, match="schema version"):
        verify_evidence(manifest, store, expected_schema_version="other_schema")


def test_payload_schema_mismatch_fails_closed(tmp_path: Path) -> None:
    store = LocalFilesystemEvidenceStore(tmp_path / "payloads")
    manifest = store.publish(
        b'{"schema_version":"wrong_schema"}',
        artifact_id="payload-schema-test",
        artifact_type="summary",
        source_commit_sha=SOURCE_SHA,
        schema_version=SCHEMA,
        retention=retention(),
    )

    with pytest.raises(EvidenceVerificationError, match="payload schema version"):
        verify_evidence(manifest, store)


def test_manifest_is_bounded_and_rejects_unmodeled_fields() -> None:
    payload = {
        "artifact_id": "safe-manifest",
        "artifact_type": "summary",
        "source_commit_sha": SOURCE_SHA,
        "created_at": "2026-08-24T12:00:00Z",
        "content_hash": "0" * 64,
        "size": 0,
        "schema_version": SCHEMA,
        "retention": {
            "retention_class": "release",
            "retention_days": 365,
            "immutable": True,
        },
        "artifact_uri": "local://safe-manifest",
        "prompt": "must not be accepted",
    }
    with pytest.raises(ValueError):
        from app.evidence.models import EvidenceManifest

        EvidenceManifest.model_validate(payload)

    sanitized = dict(payload)
    sanitized.pop("prompt")
    serialized = json.dumps(sanitized)
    assert "prompt" not in serialized


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs: object) -> object:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        if (bucket, key) in self.objects and kwargs.get("IfNoneMatch") == "*":
            raise FileExistsError("object already exists")
        body = kwargs["Body"]
        if not isinstance(body, bytes):
            raise TypeError("fake client only accepts bytes")
        self.objects[(bucket, key)] = body
        return {}

    def get_object(self, **kwargs: object) -> Mapping[str, bytes | ReadableBody]:
        body = self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]))]
        return {"Body": io.BytesIO(body)}


def test_s3_compatible_backend_uses_immutable_put() -> None:
    client = FakeS3()
    store = S3CompatibleEvidenceStore(client, "evidence-bucket", prefix="release")
    manifest = store.publish(
        b"s3 payload",
        artifact_id="s3-test",
        artifact_type="summary",
        source_commit_sha=SOURCE_SHA,
        schema_version=SCHEMA,
        retention=retention(),
    )
    assert verify_evidence(manifest, store, expected_source_sha=SOURCE_SHA) == b"s3 payload"
    with pytest.raises(FileExistsError):
        store.publish(
            b"s3 payload",
            artifact_id="s3-test",
            artifact_type="summary",
            source_commit_sha=SOURCE_SHA,
            schema_version=SCHEMA,
            retention=retention(),
        )
