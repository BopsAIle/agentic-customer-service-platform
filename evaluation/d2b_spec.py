"""Deterministic, non-executing specification for the reviewed D2b experiment."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

D2B_SPEC_VERSION = "d2b_semantic_behavioral_matrix_v1"
D2B_APPROVAL_GATE_VERSION = "d2b_review_approval_gate_v1"
D2A_DECISION_ID = "model_compatibility_d2a_v1"
D2A_DECISION_REVISION = "064208c621048fe7cc13c15b202a557c1e6019ac"
CONTRACT_VERSION = "semantic_decision_v3"
CONTRACT_SCHEMA_HASH = "b0c7c1ddb1fe4423b528f7ce05fbc63fa117737c797149f5903d327a8de6280b"
FUNCTION_SCHEMA_HASH = "49ad87926db3b66c183000da65f528008b2021d0c040e76218a5e4c3318d2fc1"
PROMPT_HASH = "4755f6074ffc8e22281c3a73c08d187c66f0ca8a8255b2c9696f274b1ae6eba0"
DATASET_VERSION = "live_eval_v1_2"
DATASET_HASH = "d8a10741dbb90e8a4de3b09098de36c4969c0b72944d253e37c9580279064eb5"


class D2bMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    denominator: str
    interpretation: str


class D2bCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    provider: str
    role: str
    d2a_eligibility: Literal["D2A_ELIGIBLE"] = "D2A_ELIGIBLE"
    compatibility_diagnostic_id: str


class D2bExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    spec_version: str = D2B_SPEC_VERSION
    status: Literal["PREPARED_NOT_APPROVED"] = "PREPARED_NOT_APPROVED"
    experiment_id_pattern: str
    objective: str
    architecture: tuple[str, ...]
    architecture_frozen: Literal[True] = True
    direct_tool_v1_comparison_arm: Literal[False] = False
    d2a_decision_id: str = D2A_DECISION_ID
    d2a_decision_revision: str = Field(min_length=40, max_length=40)
    contract_version: str = CONTRACT_VERSION
    contract_schema_hash: str = Field(min_length=64, max_length=64)
    function_schema_hash: str = Field(min_length=64, max_length=64)
    prompt_hash: str = Field(min_length=64, max_length=64)
    dataset_version: str = DATASET_VERSION
    dataset_hash: str = Field(min_length=64, max_length=64)
    dataset_strategy: dict[str, object]
    request_configuration: dict[str, object]
    eligible_candidates: tuple[D2bCandidate, ...]
    excluded_candidates: dict[str, str]
    metrics: tuple[D2bMetric, ...]
    failure_taxonomy: tuple[str, ...]
    artifact_requirements: dict[str, object]
    privacy_constraints: tuple[str, ...]
    approval_gate_version: str = D2B_APPROVAL_GATE_VERSION
    execution_requires_review_approval: Literal[True] = True
    production_defaults_changed: Literal[False] = False

    @model_validator(mode="after")
    def validate_frozen_experiment(self) -> D2bExperimentSpec:
        if self.spec_version != D2B_SPEC_VERSION:
            raise ValueError("D2b spec version mismatch")
        if self.d2a_decision_id != D2A_DECISION_ID:
            raise ValueError("D2a decision identity mismatch")
        if self.d2a_decision_revision != D2A_DECISION_REVISION:
            raise ValueError("D2a decision revision mismatch")
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("contract version mismatch")
        if self.contract_schema_hash != CONTRACT_SCHEMA_HASH:
            raise ValueError("contract schema hash mismatch")
        if self.function_schema_hash != FUNCTION_SCHEMA_HASH:
            raise ValueError("function schema hash mismatch")
        if self.prompt_hash != PROMPT_HASH:
            raise ValueError("prompt hash mismatch")
        if self.dataset_hash != DATASET_HASH:
            raise ValueError("dataset hash mismatch")
        if self.dataset_version != DATASET_VERSION:
            raise ValueError("dataset version mismatch")
        if self.approval_gate_version != D2B_APPROVAL_GATE_VERSION:
            raise ValueError("approval gate version mismatch")
        if [candidate.model for candidate in self.eligible_candidates] != ["gpt-5.6-luna"]:
            raise ValueError("D2b candidate set must match the frozen D2a decision")
        if self.dataset_strategy != {
            "case_count": 28,
            "english_cases": 14,
            "turkish_cases": 14,
            "runs_per_case": 3,
            "measured_attempts_per_model": 84,
            "warmup_maximum_per_model": 1,
            "warmup_scored": False,
            "case_order": "deterministic_frozen_order",
            "case_mutation_allowed": False,
        }:
            raise ValueError("dataset strategy drift")
        if self.request_configuration != {
            "structured_output_mode": "function_calling",
            "reasoning_effort": "none",
            "temperature": 0.0,
            "timeout_seconds": 30.0,
            "retry_count": 0,
            "candidate_specific_contract": False,
            "candidate_specific_prompt": False,
        }:
            raise ValueError("request configuration drift")
        return self


class D2bReviewApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["APPROVED"]
    approval_gate_version: str
    spec_version: str
    decision_record_id: str
    approval_record_id: str = Field(min_length=1)


def canonical_d2b_spec() -> D2bExperimentSpec:
    """Return the frozen D2b plan; this function has no provider or artifact side effects."""

    return D2bExperimentSpec(
        experiment_id_pattern="d2b_semantic_v3_<approved_utc_timestamp>",
        objective=(
            "Evaluate behavioral quality of D2a-eligible model/runtimes while holding the accepted "
            "semantic_decision_v3 architecture fixed."
        ),
        architecture=(
            "LLM",
            "semantic_decision_v3",
            "semantic entity grounding",
            "target admissibility",
            "deterministic DecisionCompiler",
            "BusinessTargetResolver where permitted",
            "business validation",
            "policy and confirmation",
            "execution",
        ),
        d2a_decision_revision=D2A_DECISION_REVISION,
        contract_schema_hash=CONTRACT_SCHEMA_HASH,
        function_schema_hash=FUNCTION_SCHEMA_HASH,
        prompt_hash=PROMPT_HASH,
        dataset_hash=DATASET_HASH,
        dataset_strategy={
            "case_count": 28,
            "english_cases": 14,
            "turkish_cases": 14,
            "runs_per_case": 3,
            "measured_attempts_per_model": 84,
            "warmup_maximum_per_model": 1,
            "warmup_scored": False,
            "case_order": "deterministic_frozen_order",
            "case_mutation_allowed": False,
        },
        request_configuration={
            "structured_output_mode": "function_calling",
            "reasoning_effort": "none",
            "temperature": 0.0,
            "timeout_seconds": 30.0,
            "retry_count": 0,
            "candidate_specific_contract": False,
            "candidate_specific_prompt": False,
        },
        eligible_candidates=(
            D2bCandidate(
                model="gpt-5.6-luna",
                provider="official OpenAI API",
                role="hosted reference and sole initial D2b-eligible candidate",
                compatibility_diagnostic_id="structured_output_v3_openai_luna_20260813T163700Z",
            ),
        ),
        excluded_candidates={
            "qwen3.5:4b": "D2A_INELIGIBLE",
            "qwen2.5:7b-instruct": "D2A_INELIGIBLE",
            "qwen3.5:9b": "D2A_INELIGIBLE",
        },
        metrics=(
            D2bMetric(
                name="routing_correctness",
                denominator="all measured attempts and scorable attempts",
                interpretation="User-task routing after deterministic semantic processing.",
            ),
            D2bMetric(
                name="semantic_target_correctness",
                denominator="target-eligible measured attempts",
                interpretation="Model reference correctness before grounding or resolution.",
            ),
            D2bMetric(
                name="clarification_quality",
                denominator="all measured attempts",
                interpretation="Appropriate, missed, and unnecessary effective clarification.",
            ),
            D2bMetric(
                name="safety_violations",
                denominator="all measured attempts plus bounded runtime safety checks",
                interpretation="Unsafe proposals and executions remain separate metrics.",
            ),
            D2bMetric(
                name="hallucinated_identifiers",
                denominator="identifier-eligible measured attempts",
                interpretation="Concrete identifiers absent from trusted user input.",
            ),
            D2bMetric(
                name="compiler_correctness",
                denominator="all and correct-semantics eligible attempts",
                interpretation="Stage-local deterministic compiler attribution.",
            ),
            D2bMetric(
                name="resolver_correctness",
                denominator="resolver-eligible and correct-reference attempts",
                interpretation="Stage-local business target resolution attribution.",
            ),
            D2bMetric(
                name="consistency",
                denominator="eligible cases and repetitions",
                interpretation="Exact and normalized semantic repetition consistency.",
            ),
            D2bMetric(
                name="latency",
                denominator="all measured attempts",
                interpretation="Provider and end-to-end min, mean, p50, p95, and max.",
            ),
            D2bMetric(
                name="token_and_cost_accounting",
                denominator="provider responses exposing usage",
                interpretation=(
                    "Record usage when available; never infer price from a hard-coded table."
                ),
            ),
        ),
        failure_taxonomy=(
            "provider_failure",
            "timeout",
            "structured_output_transport_failure",
            "argument_decode_failure",
            "contract_validation_failure",
            "intent_mismatch",
            "target_mismatch",
            "clarification_miss",
            "hallucinated_identifier",
            "grounding_intervention",
            "target_admissibility_intervention",
            "compile_failure",
            "resolver_failure",
            "policy_or_runtime_safety_failure",
            "other",
        ),
        artifact_requirements={
            "root_pattern": "artifacts/live-eval/model-matrix/<d2b_experiment_id>/",
            "required_files": [
                "manifest.json",
                "gpt-5.6-luna/attempts.json",
                "gpt-5.6-luna/summary.json",
                "gpt-5.6-luna/summary.md",
                "comparison.json",
                "comparison.md",
            ],
            "status_required": "COMPLETE",
            "atomic_publish_required": True,
            "source_hashes_required": True,
            "artifact_sha256_required": True,
            "hash_recheck_after_validation": True,
            "model_metadata_required": [
                "exact_model_id",
                "provider",
                "runtime",
                "compatibility_diagnostic_id",
            ],
            "run_metadata_required": [
                "experiment_id",
                "source_revision",
                "contract_and_prompt_hashes",
                "dataset_hash",
                "case_schedule",
                "request_configuration",
                "call_accounting",
                "approval_record_id",
            ],
            "immutable_sources": [
                "evaluation/decisions/model_compatibility_d2a_v1.json",
                "live_eval_v1_2",
                "semantic_decision_v3 schema",
                "semantic prompt",
            ],
        },
        privacy_constraints=(
            "synthetic live_eval inputs only",
            "no credentials or authorization headers",
            "no raw provider payloads or function arguments",
            "no raw prompts or hidden reasoning",
            "no real customer content, identifiers, memory, RAG content, or production data",
            "persist only bounded case IDs, enums, stage outcomes, and structural diagnostics",
        ),
    )


def assert_execution_approved(spec: D2bExperimentSpec, approval: D2bReviewApproval | None) -> None:
    """Fail closed until a separate review creates an explicit matching approval record."""

    if approval is None:
        raise RuntimeError("D2B_REVIEW_APPROVAL_REQUIRED")
    if (
        approval.approval_gate_version != spec.approval_gate_version
        or approval.spec_version != spec.spec_version
        or approval.decision_record_id != spec.d2a_decision_id
    ):
        raise RuntimeError("D2B_REVIEW_APPROVAL_MISMATCH")
