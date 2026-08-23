from pathlib import Path

import pytest

from app.evidence.models import EvidenceRetention, EvidenceRetentionClass
from app.evidence.storage import LocalFilesystemEvidenceStore
from app.evidence.verify import EvidenceVerificationError
from scripts.validate_recovery import main


def test_recovery_script_verifies_manifest_and_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalFilesystemEvidenceStore(tmp_path / "payloads")
    manifest = store.publish(
        b'{"schema_version":"recovery-v1","summary":"bounded"}',
        artifact_id="recovery-check",
        artifact_type="summary",
        source_commit_sha="a" * 40,
        schema_version="recovery-v1",
        retention=EvidenceRetention(retention_class=EvidenceRetentionClass.STANDARD),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "validate_recovery",
            str(manifest_path),
            "--root",
            str(tmp_path / "payloads"),
            "--source-sha",
            "a" * 40,
            "--schema-version",
            "recovery-v1",
        ],
    )
    assert main() == 0


def test_recovery_verification_rejects_corrupted_payload(tmp_path: Path) -> None:
    store = LocalFilesystemEvidenceStore(tmp_path / "payloads")
    manifest = store.publish(
        b"original",
        artifact_id="corrupted-check",
        artifact_type="summary",
        source_commit_sha="b" * 40,
        schema_version="recovery-v1",
        retention=EvidenceRetention(
            retention_class=EvidenceRetentionClass.STANDARD,
            retention_days=7,
        ),
    )
    payload = tmp_path / "payloads" / "corrupted-check" / "payload"
    payload.unlink()
    payload.write_bytes(b"changed!")
    with pytest.raises(EvidenceVerificationError, match="content hash mismatch"):
        from app.evidence.verify import verify_evidence

        verify_evidence(manifest, store)
