from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from app.evidence.storage import LocalFilesystemEvidenceStore
from app.evidence.verify import EvidenceVerificationError, load_manifest, verify_evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify an immutable external evidence payload.")
    parser.add_argument("manifest", type=Path, help="Path to the Git-retained evidence manifest")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("artifacts/evidence-payloads"),
        help="Local evidence store root",
    )
    parser.add_argument("--source-sha", help="Expected source commit SHA; defaults to current HEAD")
    parser.add_argument("--schema-version", help="Expected evidence schema version")
    return parser


def _current_source_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(arguments.manifest)
        source_sha = arguments.source_sha or _current_source_sha()
        verify_evidence(
            manifest,
            LocalFilesystemEvidenceStore(arguments.root),
            expected_source_sha=source_sha,
            expected_schema_version=arguments.schema_version,
        )
    except (EvidenceVerificationError, OSError, subprocess.SubprocessError) as error:
        print(f"evidence verification failed: {error}", file=sys.stderr)
        return 1
    print(
        f"evidence verified: {manifest.artifact_id} "
        f"sha256={manifest.content_hash} size={manifest.size}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
