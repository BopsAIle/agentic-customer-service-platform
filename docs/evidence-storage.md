# External Evidence Storage

M7.5 introduces an immutable evidence-storage boundary for large evaluation and operational
payloads. Git remains the source of reproducibility metadata; external storage holds payloads that
would unnecessarily enlarge Git history.

## What Git stores

Each externally retained object has a compact `EvidenceManifest` containing only:

- artifact identity and type;
- source commit SHA;
- creation timestamp;
- SHA-256 content hash and byte size;
- schema version;
- retention class and immutability requirement; and
- an immutable `local://` or `s3://` artifact URI.

Manifests reject unmodeled fields. They must not contain prompts, customer content, provider
responses, tokens, credentials, or hidden reasoning.

## What external storage holds

Large raw attempts, evaluation dumps, trace exports, and screenshot bundles may be stored in:

- the local filesystem during development; or
- an S3-compatible, versioned object store in controlled environments.

Publication is non-overwriting and content-addressed by the manifest hash. A partial or replaced
payload is invalid.

The S3 adapter accepts an injected SDK-compatible client, so deployment environments can choose
their S3-compatible provider without adding credentials or a provider-specific dependency to the
core application.

## Verification

Verify a Git-retained manifest against a local payload store with:

```text
make verify-evidence \
  MANIFEST=path/to/manifest.json \
  ROOT=artifacts/evidence-payloads \
  SOURCE_SHA=$(git rev-parse HEAD) \
  SCHEMA_VERSION=evaluation_attempts_v1
```

The verifier loads the payload, checks the source identity and schema version, recomputes the
byte size and SHA-256 hash, and rejects self-describing JSON whose payload schema does not match
the manifest. It never prints payload contents.

The equivalent module entry point is:

```text
uv run --frozen python -m app.evidence.cli path/to/manifest.json
```

## CI and retention

Evaluation jobs may upload generated payloads as immutable CI artifacts while retaining compact
manifests and summaries as the reviewable evidence envelope. The upload location, retention class,
source SHA, and hash must remain bound by the manifest. Release evidence should use the longest
practical immutable retention supported by the selected store.

Historical artifacts already committed to the repository are not rewritten or deleted by M7.5.
Future producers should publish payloads through `EvidenceStore`, retain the returned manifest in
Git or a release record, and run independent verification before classifying evidence complete.

## Privacy boundary

Storage does not make sensitive evidence safe by itself. Producers must apply bounded projections
and privacy scanning before publication. Raw prompts, unrestricted user data, secrets, hidden
reasoning, and provider payloads are not valid evidence payloads for this repository.
