# Semantic V3 model/runtime compatibility decision

- Status: **ACCEPTED**
- Decision date: 2026-08-13
- Machine record: `evaluation/decisions/model_compatibility_d2a_v1.json`
- Eligibility rules: `d2a_compatibility_gate_v1`
- Contract: `semantic_decision_v3`
- Structured-output mode: `function_calling`
- D2b eligible set: `gpt-5.6-luna`

## Scope

D2a asks only whether a candidate model/runtime can reliably construct the fixed
`SemanticDecisionV3` contract under the 30-second, zero-retry protocol. It does not compare
architectures or establish routing quality, safety quality, cost leadership, deployment approval,
or general model quality. The semantic architecture remained frozen. At the D2a decision date,
`direct_tool_v1` remained the production runtime default; M6.73 later changed the runnable default
to `semantic_decision_v3` without changing this frozen compatibility evidence.

All candidates used the same schema, function-calling transport schema, prompt, eight-case
structured-contract subset, three repetitions, temperature zero, reasoning disabled, and no
retries. The `live_eval_v1_1` and `live_eval_v1_2` representations of this exact subset have the
same canonical hash:
`850f8adfa6ce890f4a6db1edadb87d9ac2549df4140d8bca5ee88beb12bb521e`.

## Eligibility rule

`D2A_ELIGIBLE` requires all of the following over 24 measured attempts:

- provider success at least 23/24;
- decoded arguments at least 23/24;
- typed `SemanticDecisionV3` at least 23/24;
- at most one timeout;
- no systematic transport/decode failure;
- no repeated fundamental contract-shape failure; and
- a valid experiment.

Results that narrowly miss the gate without an ineligibility condition require review. A candidate
is ineligible with at most 20 typed decisions, materially low provider success, two or more
timeouts, or systematic transport/decode/target/root-shape incompatibility. Thresholds were
pre-registered before the new local runs.

## Results

| Candidate | Runtime identity | Typed V3 | Main evidence | Decision |
| --- | --- | ---: | --- | --- |
| GPT-5.6 Luna | Official OpenAI API; provider-managed digest/quantization | 24/24 | No validation failures | `D2A_ELIGIBLE` |
| Qwen3.5 4B | Ollama 0.32.6; `2a654d…eefd`; Q4_K_M | 3/24 | 21 × `model_attributes_type@target` | `D2A_INELIGIBLE` |
| Qwen2.5 7B Instruct | Ollama 0.32.6; `845dbd…697e`; Q4_K_M | 0/24 | 24 × `model_type@<root>`; no structured calls | `D2A_INELIGIBLE` |
| Qwen3.5 9B | Ollama 0.32.6; `6488c9…3ea7`; Q4_K_M | 0/24 | 21 × target shape, 6 × missing intent, 3 provider errors | `D2A_INELIGIBLE` |

The Qwen findings apply specifically to these exact local model builds under Ollama,
`function_calling`, `semantic_decision_v3`, and the fixed D2a runtime budget. They do not show that
the model families are universally incompatible or generally low quality. Luna is the sole D2b
eligible candidate and remains a hosted reference, not an automatic production-model selection.

## Immutable evidence

The decision uses the following canonical diagnostic IDs and SHA-256 triples in
`attempts.json / summary.json / summary.md` order:

- `structured_output_v3_openai_luna_20260813T163700Z`:
  `ca29727e949580e2261d707d8e9d7d1b25b9358a921dca6a3fcf34030834e7bd` /
  `28cd194448f9513068e03b435611bd292da257f9b38969e49b8ea4e9b8169b4d` /
  `2e690ed6a63db87d698d27e6f011212cfd7d2fb0e0effceffbc38c1630c94562`.
- `structured_output_v3_qwen3_5_4b_20260813T163044Z`:
  `952b0d6684f159a51722cd3c11022acfa0c8a3b9d7555c85288933effbe8a81a` /
  `bc393be492185a402081a2a4a1aeba4371ca5bbfcd1476465088a63655e5b693` /
  `77f6f467584bf88c7b49a31af2a1d98b690fffe08be7c5c89b851e25086543ad`.
- `d2a_qwen2_5_7b_20260813T200426Z`:
  `df2972c6e1b69044760fec059a9d25b6eeec39977cd02038b552006e9af435dd` /
  `cd0522089897b61e58445a2eb0b5476a376c93f2e8dc8d8f60dd4a11b2d89d3d` /
  `bd1ea678469be342ac344ec5946954cfa71376fac10aeefd925ea657e77b8dc1`.
- `d2a_qwen3_5_9b_20260813T200809Z`:
  `44e1f8c1a9c53593b9f2dda8c0666222b6a3a3cc6895eb021bc8878e7152444a` /
  `9414849e5ef49a582bd4945bed4aaf8c55a044102fab626db53a1d5f4a77596c` /
  `b7e7ca14e2f7890cb6125f95e844172471d79f43bc9f219b697e82fde0443f86`.

Historical artifacts were not rewritten or copied into the repository. D2a.1's invalid warmup run
remains excluded historical evidence. The freeze made no model calls and changed no model output,
schema, prompt, dataset, product behavior, or production default.
