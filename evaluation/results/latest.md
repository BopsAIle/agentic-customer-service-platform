# Agent Evaluation Report

- Run: `eval-8e24edd009bc`
- Dataset: `evaluation/datasets`
- Seed: `0`
- Scenarios: 110
- Overall pass rate: 100.0%

## Metrics

| Metric | Result |
| --- | ---: |
| Intent Accuracy | 100.0% |
| Request Type Accuracy | 100.0% |
| Tool Selection Accuracy | 100.0% |
| Tool Argument Accuracy | 100.0% |
| Task Completion Rate | 100.0% |
| Confirmation Compliance | 100.0% |
| Unauthorized Action Rate | 0.0% |
| Escalation Accuracy | 100.0% |
| Citation Integrity | 100.0% |
| Failure Recovery Rate | 100.0% |
| Memory Retrieval Accuracy | 100.0% |
| Memory Write Policy Compliance | 100.0% |
| Memory Conflict Resolution Accuracy | 100.0% |
| Failure Recovery Accuracy | 100.0% |
| Degraded Mode Accuracy | 100.0% |
| Retry Policy Compliance | 100.0% |
| Duplicate Write Rate | 0.0% |

## Category breakdown

| Category | Scenarios | Pass rate |
| --- | ---: | ---: |
| ambiguity | 2 | 100.0% |
| confirmation | 17 | 100.0% |
| degraded_mode | 7 | 100.0% |
| failure_recovery | 20 | 100.0% |
| human_escalation | 10 | 100.0% |
| knowledge | 11 | 100.0% |
| knowledge_and_action | 1 | 100.0% |
| memory | 11 | 100.0% |
| multi_turn | 2 | 100.0% |
| ownership | 4 | 100.0% |
| policy | 1 | 100.0% |
| prompt_injection | 4 | 100.0% |
| read_action | 10 | 100.0% |
| write_action | 10 | 100.0% |

## Failed scenarios

No failed scenarios.

## Latency

- Mean: 32.94 ms
- Max: 77.64 ms
