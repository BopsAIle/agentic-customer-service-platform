"""Validate an immutable evidence manifest and its local payload."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.evidence.storage import LocalFilesystemEvidenceStore
from app.evidence.verify import EvidenceVerificationError, load_manifest, verify_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path("artifacts/evidence-payloads"))
    parser.add_argument("--source-sha")
    parser.add_argument("--schema-version")
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        verify_evidence(
            manifest,
            LocalFilesystemEvidenceStore(args.root),
            expected_source_sha=args.source_sha,
            expected_schema_version=args.schema_version,
        )
    except EvidenceVerificationError as error:
        print(f"recovery evidence validation: FAIL ({error})")
        return 1
    print("recovery evidence validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
