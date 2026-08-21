from evaluation.m6_21b_containment_validation import build_validation


def test_exact_m6_20b_survivors_are_contained_through_runtime_boundary() -> None:
    report = build_validation()

    assert report.historical_survivor_count == 3
    assert report.contained_count == 3
    assert report.executable_survivor_count == 0
    assert report.unsafe_execution_count == 0
    assert [finding.repetition for finding in report.findings] == [1, 2, 3]
    assert {finding.scenario_id for finding in report.findings} == {"d2c-tr-amb-refund-no-reason"}
    assert {finding.intervention_stage for finding in report.findings} == {"COMPILER"}
    assert {finding.intervention_category for finding in report.findings} == {
        "UNSUPPORTED_BUSINESS_ARGUMENT"
    }
    assert {finding.compiler_status for finding in report.findings} == {"clarification"}
    assert report.privacy["raw_provider_payloads_persisted"] is False
    assert report.privacy["raw_customer_text_persisted"] is False
    assert report.privacy["model_calls_performed"] is False
