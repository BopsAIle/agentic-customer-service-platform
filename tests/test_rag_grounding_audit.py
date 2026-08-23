from evaluation.rag_grounding_audit import grounding_cases, run_audit


def test_grounding_audit_has_twenty_deterministic_cases() -> None:
    cases = grounding_cases()

    assert len(cases) == 20
    assert {case.case_id for case in cases} >= {
        "refund-policy",
        "hallucination-ceo-phone",
        "refund-conflict",
        "empty-refund",
    }


def test_grounding_audit_passes_without_model_calls() -> None:
    audit = run_audit()

    assert audit.passed_count == audit.case_count == 20
    assert audit.failed_count == 0
    assert audit.unsupported_claim_count == 0
    assert audit.model_calls_performed == 0
