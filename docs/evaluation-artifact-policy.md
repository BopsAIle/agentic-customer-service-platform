# Evaluation Artifact Retention Policy

This policy applies to evaluation evidence produced after its adoption. Historical artifacts
already committed to the repository remain immutable; this milestone does not move, rewrite, or
delete them.

The executable manifest and storage adapters are documented in
[`docs/evidence-storage.md`](evidence-storage.md).

## Evidence retained in Git

Each published evaluation should keep a compact, reviewable evidence envelope in Git:

- the artifact manifest and schema identity;
- machine-readable and human-readable summaries;
- SHA-256 hashes for every evidence object, including externally retained objects;
- source revision, contract, dataset, schedule, scorer, and environment identities where relevant;
- approval and execution identity when the evaluation is prospective; and
- an immutable artifact URI or release location for evidence stored outside Git.

These records must be sufficient to identify the run, validate artifact relationships, and detect
replacement or corruption without requiring large raw payloads in normal Git history.

## Large raw evidence

Future large `attempts.json` files, provider-independent execution dumps, and similarly bulky raw
records may be retained outside the Git object database in one of the following approved locations:

- immutable GitHub Actions artifacts with an explicit retention period;
- a GitHub Release asset bound to the source revision or release candidate;
- access-controlled object storage with versioning and retention protection; or
- Git LFS when the repository explicitly adopts and supports it.

The selected location must be recorded in the manifest. A mutable branch URL, an undocumented local
path, or an unversioned object key is not an acceptable evidence location.

## Integrity and publication

Published evidence must be non-overwriting and content-addressed by SHA-256. The manifest must bind
the source revision and all applicable contract, dataset, scorer, schedule, environment, and image
identities. Publication must be atomic: partial outputs are invalid and must not be presented as a
complete run. Independent validation must be able to recompute hashes and verify the manifest-to-
artifact relationships.

## Privacy and security

Evaluation evidence must not contain credentials, environment dumps, raw hidden prompts, hidden
reasoning, unrestricted customer records, or sensitive provider payloads. Projections and summaries
must use allowlisted bounded fields. Raw evidence requires the same privacy scan as Git-retained
evidence before publication, plus access controls appropriate to its sensitivity.

## Retention and availability

The manifest records the retention class and expected availability window for externally stored
objects. Release-gating evidence should use the longest practical immutable retention supported by
the chosen store. If an external object expires, the Git-retained manifest and hashes remain valid
identity records, but the evidence must be marked unavailable rather than silently regenerated.

## Historical reproducibility

Existing committed evidence remains at its current paths with its current bytes and hashes. New
policy adoption does not retroactively rename, compact, or reclassify historical runs. Historical
tools may continue to consume those artifacts directly; future tools should support the compact
manifest plus immutable external-object model described here.
